"""The two translation directions.

HEAR  (incoming): meeting audio -> speech recognition -> translate to MY language -> overlay captions (+ optional voice)
SPEAK (outgoing): my microphone -> speech recognition -> translate to the MEETING language -> voice into the virtual mic
                  When SPEAK is switched off, my normal voice passes straight through to the virtual mic,
                  so people still hear me without changing Zoom's settings.
"""
import collections
import queue
import threading
import time

import numpy as np

from . import audio, languages, tts
from .vad import Segmenter


def glossary_terms(glossary):
    terms = [line.split("=")[0].strip() for line in glossary.splitlines() if line.strip()]
    return ", ".join(t for t in terms if t)[:400]


class Direction:
    def __init__(self, kind, cfg, stt, translator, emit, log):
        self.kind = kind  # "in" or "out"
        self.cfg, self.stt, self.translator, self.emit, self.log = cfg, stt, translator, emit, log
        self.translating = False
        self.capture = None
        self.output = None
        self.seg = None
        self.work = queue.Queue()
        self.context = collections.deque(maxlen=6)
        self.worker = None
        self.running = False
        self.gate_echo = False
        self.lock = threading.Lock()

    # ---------- lifecycle ----------
    def _open(self):
        """Open the capture + output devices for this direction."""
        c = self.cfg
        self.seg = Segmenter(sensitivity=float(c["sensitivity"]), silence_ms=int(c["silence_ms"]))
        if self.kind == "in":
            src = audio.find_mic(c["in_source"], loopback=True)
            self.output = audio.Output(audio.find_speaker(c["in_voice_output"]), self._dev_error)
            # if we read translations aloud on the same speakers we are capturing, pause capture while speaking
            self.gate_echo = getattr(src, "name", "") == getattr(self.output.device, "name", "")
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
        with self.work.mutex:
            self.work.queue.clear()

    def set_translating(self, on):
        """Main ON/OFF switch for this direction."""
        audio._com_init()
        with self.lock:
            self.translating = on
            need_devices = on or (self.kind == "out" and self.cfg["out_passthrough"] and self.cfg["out_virtual"])
            try:
                if need_devices and not self.running:
                    self._open()
                elif not need_devices and self.running:
                    self._close()
            except Exception as e:
                self.translating = False
                self._close()
                self.log(f"Could not start audio: {e}")
                self.emit({"type": "state"})
                return False
        if on:
            threading.Thread(target=self.stt.load, daemon=True).start()
        self.emit({"type": "state"})
        return True

    def restart(self):
        """Re-open devices after settings changed."""
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
            self.output.skip()

    def _dev_error(self, e):
        self.log(f"Audio device error ({'meeting' if self.kind == 'in' else 'microphone'}): {e}")
        self.translating = False
        self._close()
        self.emit({"type": "state"})

    # ---------- audio path ----------
    def _on_block(self, block48):
        if self.kind == "out" and not self.translating:
            if self.output:
                self.output.stream(block48)        # normal voice pass-through
            return
        if not self.translating:
            return
        if self.gate_echo and self.output and (self.output.busy or time.time() - self.output.last_voice < 0.4):
            return                                  # ignore our own translated voice
        seg = self.seg.feed(audio.to_16k(block48))
        speaking = self.seg.speaking
        if speaking != getattr(self, "_was_speaking", False):
            self._was_speaking = speaking
            self.emit({"type": "speaking", "dir": self.kind, "on": speaking})
        if seg is not None:
            if self.work.qsize() >= 4:
                self.log("Falling behind. Pick a smaller speech model (e.g. 'base') in AI engines.")
                try:
                    self.work.get_nowait()
                except queue.Empty:
                    pass
            self.work.put((time.time(), seg))

    def _work_loop(self):
        while True:
            t_end, seg = self.work.get()
            if not self.translating:
                continue
            try:
                self._process(t_end, seg)
            except Exception as e:
                self.log(f"Error: {e}")

    def _process(self, t_end, seg):
        c = self.cfg
        hint = c["in_speaker_lang"] if self.kind == "in" else c["out_my_lang"]
        tgt = c["in_lang"] if self.kind == "in" else c["out_lang"]
        text, src, prob = self.stt.transcribe(seg.astype(np.float32), hint if hint != "auto" else None,
                                              glossary_terms(c["glossary"]))
        if not text:
            return
        src = src or hint
        try:
            tr = self.translator.translate(text, src, tgt, "\n".join(self.context))
        except Exception as e:
            self.log(f"Translation failed: {e}")
            tr = None
        self.context.append(text)
        latency = time.time() - t_end
        self.emit({"type": "caption", "dir": self.kind, "orig": text, "src": src, "text": tr,
                   "tgt": tgt, "latency": latency, "t": time.time()})
        speak = tr and (c["in_voice"] if self.kind == "in" else True)
        if speak and self.output:
            gender = c["in_gender"] if self.kind == "in" else c["out_gender"]
            try:
                clip = tts.synthesize(tr, tgt, gender, float(c["rate"]))
                if clip is None:
                    self.log(f"No voice available for {languages.name(tgt)}; showing captions only.")
                elif self.output:
                    self.output.play_clip(clip)
            except Exception as e:
                self.log(f"Voice failed: {e}")
