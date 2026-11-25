"""The two translation directions.

HEAR  (incoming): meeting audio -> speech recognition -> translate to MY language -> overlay captions (+ optional voice)
SPEAK (outgoing): my microphone -> speech recognition -> translate to the MEETING language -> voice into the virtual mic
                  When SPEAK is off, my normal voice passes straight through to the virtual mic (the overlay shows this).

Speed: while someone is still talking, a live caption is refreshed about once a second from the sentence so far;
the finished sentence then replaces it with the full-quality version. Nothing is ever dropped: when processing falls
behind, waiting sentences are merged and handled together.
"""
import collections
import difflib
import queue
import re
import statistics
import threading
import time

import numpy as np

from . import audio, languages, tts
from .vad import Segmenter

LIVE_EVERY = 0.8        # seconds between live caption refreshes
LIVE_MIN_AUDIO = 0.8    # seconds of speech before the first live caption


def glossary_terms(glossary):
    terms = [line.split("=")[0].strip() for line in glossary.splitlines() if line.strip()]
    return ", ".join(t for t in terms if t)[:400]


def _norm(t):
    return re.sub(r"[\W_]+", " ", (t or "").lower()).strip()


def similar(a, b):
    a, b = _norm(a), _norm(b)
    if not a or not b:
        return False
    if a in b or b in a:
        return min(len(a), len(b)) >= 4
    return difflib.SequenceMatcher(None, a, b).ratio() >= 0.6


class EchoMemory:
    """Remembers what was recently heard from the meeting and what we recently said aloud,
    so neither direction translates the other's sound coming back through speakers or microphone."""

    def __init__(self):
        self.items = collections.deque(maxlen=60)   # (time, kind, text)
        self.lock = threading.Lock()

    def add(self, kind, text):
        with self.lock:
            self.items.append((time.time(), kind, text))

    def seen(self, kinds, text, within):
        now = time.time()
        with self.lock:
            return any(k in kinds and now - t < within and similar(text, x) for t, k, x in self.items)


class Stats:
    def __init__(self):
        self.d = collections.defaultdict(lambda: collections.deque(maxlen=50))

    def add(self, key, seconds):
        self.d[key].append(seconds)

    def summary(self):
        out = {}
        for k, v in list(self.d.items()):
            if v:
                s = sorted(v)
                out[k] = (statistics.median(s), s[min(len(s) - 1, int(round(0.95 * (len(s) - 1))))], len(s))
        return out


class Direction:
    def __init__(self, kind, cfg, stt, translator, emit, log, echo, stats):
        self.kind = kind  # "in" or "out"
        self.cfg, self.stt, self.translator, self.emit, self.log = cfg, stt, translator, emit, log
        self.echo, self.stats = echo, stats
        self.translating = False
        self.capture = self.output = self.seg = None
        self.resampler = audio.Resampler()
        self.work = queue.Queue()
        self.context = collections.deque(maxlen=6)
        self.lang_hist = collections.deque(maxlen=6)
        self.worker = None
        self.running = False
        self.lock = threading.Lock()
        self.live_busy = False
        self.live_last = 0.0
        self.live_text = ""
        self._was_speaking = False

    # ---------- lifecycle ----------
    @property
    def passthrough(self):
        return self.kind == "out" and self.running and not self.translating

    def _open(self):
        c = self.cfg
        self.seg = Segmenter(sensitivity=float(c["sensitivity"]), silence_ms=int(c["silence_ms"]),
                             max_seconds=float(c.get("max_seconds", 6)))
        self.resampler = audio.Resampler()
        if self.kind == "in":
            src = audio.find_mic(c["in_source"], loopback=True)
            self.output = audio.Output(audio.find_speaker(c["in_voice_output"]), self._dev_error)
            self.log(f"Hearing the meeting from: {src.name}")
        else:
            src = audio.find_mic(c["out_mic"], loopback=False)
            if not c["out_virtual"]:
                raise RuntimeError("Choose the virtual microphone output first (VB-Cable on Windows, BlackHole on Mac).")
            self.output = audio.Output(audio.find_speaker(c["out_virtual"]), self._dev_error)
            self.log(f"My microphone: {src.name}  ->  virtual mic: {self.output.device.name}")
        self.capture = audio.Capture(src, self._on_block, self._dev_error)
        self.output.start()
        self.capture.start()
        self.running = True
        if self.worker is None or not self.worker.is_alive():
            self.worker = threading.Thread(target=self._work_loop, daemon=True)
            self.worker.start()

    def _close(self):
        self.running = False
        for d in (self.capture, self.output):
            if d:
                d.stop()
        self.capture = self.output = None

    def set_translating(self, on):
        """Main ON/OFF switch. Called on a background thread (opening audio devices can take a moment)."""
        audio._com_init()
        with self.lock:
            self.translating = on
            need = on or (self.kind == "out" and self.cfg["out_passthrough"] and self.cfg["out_virtual"])
            try:
                if need and not self.running:
                    self._open()
                elif not need and self.running:
                    self._close()
            except Exception as e:
                self.translating = False
                self._close()
                self.log(f"Could not start audio: {e}")
        if on and not self.stt.ready():
            threading.Thread(target=self.stt.load, daemon=True).start()
        self.emit({"type": "state"})
        return self.translating == on

    def restart(self):
        with self.lock:
            was = self.running
            self._close()
        if was:
            self.set_translating(self.translating)

    def shutdown(self):
        self.translating = False
        self._close()

    def skip_voice(self):
        if self.output:
            self.output.skip_to_latest()

    def _dev_error(self, e):
        self.log(f"Audio device error ({'meeting' if self.kind == 'in' else 'microphone'}): {e}")
        self.translating = False
        self._close()
        self.emit({"type": "state"})

    @property
    def status(self):
        if not self.translating:
            return "off"
        return "on" if self.stt.ready() else "loading"

    # ---------- audio path ----------
    def _on_block(self, block48):
        if self.kind == "out" and not self.translating:
            if self.output:
                self.output.stream(block48)        # your normal voice passes through
            return
        if not self.translating:
            return
        block16 = self.resampler(block48)
        seg = self.seg.feed(block16)
        speaking = self.seg.speaking
        if speaking != self._was_speaking:
            self._was_speaking = speaking
            self.emit({"type": "speaking", "dir": self.kind, "on": speaking})
            if not speaking:
                self.live_text = ""
        if seg is not None:
            self.work.put((time.time(), seg))
        elif speaking and self.cfg.get("live_captions", True):
            self._maybe_live()

    def _maybe_live(self):
        now = time.time()
        if self.live_busy or now - self.live_last < LIVE_EVERY or not self.stt.ready() or not self.work.empty():
            return
        cur = self.seg.current()
        if cur is None or len(cur) < LIVE_MIN_AUDIO * 16000:
            return
        self.live_busy, self.live_last = True, now
        threading.Thread(target=self._live, args=(cur[-16000 * 8:].copy(), now), daemon=True).start()

    def _live(self, clip, t0):
        try:
            c = self.cfg
            hint = c["in_speaker_lang"] if self.kind == "in" else c["out_my_lang"]
            text, src, prob = self.stt.transcribe(clip, None if hint == "auto" else hint, glossary_terms(c["glossary"]), quick=True)
            if not text or text == self.live_text or not self.seg or not self.seg.speaking:
                return
            self.live_text = text
            src = self._smooth_lang(src, prob, hint, record=False)
            tgt = c["in_lang"] if self.kind == "in" else c["out_lang"]
            try:
                tr = self.translator.translate(text, src, tgt, "\n".join(self.context))
            except Exception:
                tr = None
            if self.seg and self.seg.speaking:
                lag = time.time() - t0
                self.stats.add(f"{self.kind}_live", lag)
                self.emit({"type": "live", "dir": self.kind, "orig": text, "src": src, "text": tr, "tgt": tgt, "lag": lag})
        except Exception:
            pass
        finally:
            self.live_busy = False

    # ---------- finished sentences ----------
    def _work_loop(self):
        while True:
            t_end, seg = self.work.get()
            # waiting for the speech model: keep everything, nothing is dropped
            while self.translating and not self.stt.ready():
                time.sleep(0.3)
            # fell behind: merge what is waiting into one piece instead of deleting it
            merged = [seg]
            while not self.work.empty() and sum(len(s) for s in merged) < 16000 * 15:
                t_end, nxt = self.work.get_nowait()
                merged.append(np.zeros(1600, dtype=np.float32))
                merged.append(nxt)
            if len(merged) > 1:
                self.log("Catching up: joined waiting sentences together.")
                seg = np.concatenate(merged)
            if not self.translating:
                continue
            try:
                self._process(t_end, seg)
            except Exception as e:
                self.log(f"Error: {e}")

    def _smooth_lang(self, src, prob, hint, record=True):
        if hint and hint != "auto":
            return hint
        if src and prob >= 0.6:
            if record:
                self.lang_hist.append(src)
            return src
        if self.lang_hist:  # unsure: use the language heard most in recent sentences
            return collections.Counter(self.lang_hist).most_common(1)[0][0]
        return src

    def _process(self, t_end, seg):
        c = self.cfg
        hint = c["in_speaker_lang"] if self.kind == "in" else c["out_my_lang"]
        tgt = c["in_lang"] if self.kind == "in" else c["out_lang"]
        text, src, prob = self.stt.transcribe(seg.astype(np.float32), None if hint == "auto" else hint, glossary_terms(c["glossary"]))
        if not text:
            return
        # echo filters
        if self.kind == "in" and self.echo.seen({"said_in"}, text, 25):
            return  # our own read-aloud translation coming back through the speakers
        if self.kind == "out" and not c.get("out_headphones") and self.echo.seen({"heard_in"}, text, 20):
            self.log("Ignored: your microphone picked up the meeting's sound (use headphones to avoid this).")
            return
        src = self._smooth_lang(src, prob, hint)
        if self.kind == "in":
            self.echo.add("heard_in", text)
        try:
            tr = self.translator.translate(text, src, tgt, "\n".join(self.context))
        except Exception as e:
            self.log(f"Translation failed: {e}")
            tr = None
        self.context.append(text)
        cap_lag = time.time() - t_end
        self.stats.add(f"{self.kind}_caption", cap_lag)
        self.emit({"type": "caption", "dir": self.kind, "orig": text, "src": src, "text": tr, "tgt": tgt,
                   "latency": cap_lag, "t": time.time(), "prob": prob})
        if self.kind == "out":
            self._speak_out(tr, tgt, seg, t_end)
        elif tr and c["in_voice"]:
            self._speak(tr, tgt, c["in_gender"], t_end)
            self.echo.add("said_in", tr)

    def _speak(self, text, lang, gender, t_end):
        out = self.output
        if not out:
            return False
        first = True
        for clause in tts.split_clauses(text):
            boost = min(1.6, float(self.cfg["rate"]) * (1 + 0.15 * out.backlog()))   # speed up when behind
            try:
                clip = tts.synthesize(clause, lang, gender, boost)
            except Exception as e:
                self.log(f"Voice failed: {e}")
                return not first
            if clip is None:
                self.log(f"No voice available for {languages.name(lang)}; showing captions only.")
                return False
            if first:
                k = f"{self.kind}_voice"
                out.play_clip(clip, on_start=lambda k=k: self.stats.add(k, time.time() - t_end))
                first = False
            else:
                out.play_clip(clip)
        return True

    def _speak_out(self, tr, tgt, seg, t_end):
        ok = bool(tr) and self._speak(tr, tgt, self.cfg["out_gender"], t_end)
        if not ok and self.output:
            # never leave the meeting in silence: send your own recorded words instead
            self.log("Sent your original voice for this sentence (translation or voice failed).")
            self.output.play_clip(audio.to_48k(seg.astype(np.float32)))
