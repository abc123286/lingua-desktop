"""Unit tests that need only numpy (run in CI before building). Run: python -m pytest -q tests"""
import os
import sys
import time

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from lingua import audio, languages as L, translate, tts  # noqa: E402
from lingua.engine import EchoMemory, Stats, similar  # noqa: E402
from lingua.stt import is_junk  # noqa: E402
from lingua.vad import Segmenter  # noqa: E402

SR = 16000
rng = np.random.default_rng(0)


def tone(sec, amp=0.2):
    t = np.arange(int(sec * SR)) / SR
    return (amp * np.sin(2 * np.pi * 220 * t)).astype(np.float32)


def noise(sec, amp=0.002):
    return rng.normal(0, amp, int(sec * SR)).astype(np.float32)


def run(seg, stream):
    out = []
    for i in range(0, len(stream), 800):
        r = seg.feed(stream[i:i + 800])
        if r is not None:
            out.append(len(r) / SR)
    return out


def test_short_words_kept():
    # "ya" / "no" are often 200-300 ms long
    for dur in (0.2, 0.3):
        assert len(run(Segmenter(), np.concatenate([noise(1), tone(dur), noise(1)]))) == 1, dur


def test_long_speech_is_cut_not_lost():
    out = run(Segmenter(max_seconds=6), tone(14))
    assert out and max(out) <= 6.1


def test_current_sentence_available_for_live_captions():
    s = Segmenter()
    for i in range(0, SR, 800):
        s.feed(tone(1)[i:i + 800])
    assert s.speaking and s.current() is not None and len(s.current()) > SR * 0.8


def test_phrase_filter_keeps_everyday_replies():
    for t in ("Thank you.", "Bye.", "Terima kasih.", "好", "是", "对", "係", "Ya", "OK"):
        assert not is_junk(t), t
    for t in ("Thanks for watching!", "", "a", "字幕由Amara.org社区提供"):
        assert is_junk(t), t


def test_language_mapping():
    assert L.to_whisper("yue", "base") == "zh" and L.to_whisper("yue", "large-v3") == "yue"
    assert L.to_whisper("fil") == "tl" and L.to_whisper("auto") is None and L.to_whisper("x-iban") is None
    assert L.from_whisper("zh") == "zh-CN" and L.whisper_name_to_code("Malay") == "ms"
    assert L.same_language("pt-BR", "pt-PT") and not L.same_language("zh-CN", "zh-TW") and not L.same_language("ms", "id")
    assert L.google_code("fil") == "tl" and L.tts_locale("yue") == "zh-HK"
    assert len({r[0] for r in L.LANGS}) == len(L.LANGS)


def test_glossary_protection_round_trip():
    g = translate.parse_glossary("Seri Maju\ninverter aircond = penghawa dingin inverter")
    body, restore = translate.protect("Seri Maju sells inverter aircond units", g)
    assert "Seri Maju" not in body and "inverter aircond" not in body
    fake = body.replace("sells", "menjual").replace("units", "unit")      # what a translator would return
    assert translate.unprotect(fake, restore) == "Seri Maju menjual penghawa dingin inverter unit"
    spaced = body.replace("QZX0QZX", "QZX 0 QZX")                         # translators sometimes add spaces
    assert "penghawa dingin inverter" in translate.unprotect(spaced, restore) or "Seri Maju" in translate.unprotect(spaced, restore)


def test_mymemory_chunks_long_text():
    text = ("This is a sentence. " * 60).strip()
    parts = translate._chunks(text, 450)
    assert all(len(p) <= 450 for p in parts) and " ".join(parts).replace("  ", " ") == text


def test_translator_falls_back_and_reports_engine():
    used = []
    tr = translate.Translator({"glossary": "", "translator": "google_free"}, lambda m: None, on_engine=used.append)
    tr.google.translate = lambda *a: (_ for _ in ()).throw(RuntimeError("TooManyRequests (429)"))
    tr.mymemory.translate = lambda *a: "Selamat pagi"
    real_sleep = translate.time.sleep
    translate.time.sleep = lambda s: None
    try:
        assert tr.translate("Good morning", "en", "ms") == "Selamat pagi" and used == ["MyMemory"]
    finally:
        translate.time.sleep = real_sleep


def test_echo_memory():
    e = EchoMemory()
    e.add("heard_in", "Can everyone see my screen now?")
    assert e.seen({"heard_in"}, "can everyone see my screen now", 20)
    assert not e.seen({"heard_in"}, "Let's talk about the Kelantan targets", 20)
    assert not e.seen({"said_in"}, "Can everyone see my screen now?", 20)
    assert similar("Selamat pagi semua", "selamat pagi semua!") and not similar("ya", "tidak")


def test_stats_percentiles():
    s = Stats()
    for v in (0.5, 0.6, 0.7, 3.0):
        s.add("in_caption", v)
    med, p95, n = s.summary()["in_caption"]
    assert n == 4 and 0.6 <= med <= 0.7 and p95 == 3.0


def test_resampler_filters_aliasing():
    t = np.arange(48000) / 48000
    r1, r2 = audio.Resampler(), audio.Resampler()
    speech = np.concatenate([r1(np.sin(2 * np.pi * 440 * t[i:i + 2400]).astype(np.float32)) for i in range(0, 48000, 2400)])
    alias = np.concatenate([r2(np.sin(2 * np.pi * 15000 * t[i:i + 2400]).astype(np.float32)) for i in range(0, 48000, 2400)])
    assert len(speech) == 16000
    assert np.sqrt((speech[200:] ** 2).mean()) > 0.6 and np.sqrt((alias[200:] ** 2).mean()) < 0.02
    assert len(audio.to_48k(np.zeros(SR, np.float32))) == 48000


def test_clause_split_for_faster_voice():
    parts = tts.split_clauses("Selamat pagi semua. Hari ini kita akan semak angka jualan, kemudian kita rancang promosi bulan depan.")
    assert len(parts) >= 2 and " ".join(parts).replace("  ", " ").startswith("Selamat pagi semua.")


# ---------------- engine behaviour (fake speech/translation/audio) ----------------
from lingua import config, engine  # noqa: E402


class FakeSTT:
    def __init__(self, texts, ready=True):
        self.texts, self._ready, self.calls = list(texts), ready, 0

    def ready(self):
        return self._ready

    def load(self):
        self._ready = True
        return True

    def transcribe(self, audio16k, hint=None, prompt=None, quick=False):
        self.calls += 1
        return (self.texts.pop(0) if self.texts else "hello"), "en", 0.95


class FakeOut:
    def __init__(self):
        self.clips = []

    def backlog(self):
        return 0

    def play_clip(self, clip, on_start=None):
        self.clips.append(clip)
        if on_start:
            on_start()


def make(kind, stt, translate_fn, cfg_over=None):
    cfg = dict(config.DEFAULTS, **(cfg_over or {}))
    tr = type("T", (), {"translate": staticmethod(translate_fn)})()
    events, logs = [], []
    d = engine.Direction(kind, cfg, stt, tr, events.append, logs.append, engine.EchoMemory(), engine.Stats())
    d.translating, d.output = True, FakeOut()
    return d, events, logs


def test_translation_failure_sends_original_voice():
    def boom(*a):
        raise RuntimeError("offline")
    d, ev, logs = make("out", FakeSTT(["Selamat pagi"]), boom)
    seg = tone(1.0)
    d._process(time.time(), seg)
    assert len(d.output.clips) == 1 and len(d.output.clips[0]) == len(seg) * 3       # your own words, at 48 kHz
    assert any("original voice" in m for m in logs)


def test_translated_voice_and_latency_recorded():
    tts.synthesize = lambda text, code, g, r: np.zeros(4800, np.float32)
    d, ev, logs = make("out", FakeSTT(["Selamat pagi semua. Kita mula sekarang."]), lambda t, s, g, c: "Good morning everyone. We start now.")
    d._process(time.time(), tone(1.0))
    assert len(d.output.clips) == 2                                                    # spoken clause by clause
    assert "out_voice" in d.stats.summary() and "out_caption" in d.stats.summary()


def test_nothing_dropped_when_busy_or_loading():
    import threading
    tts.synthesize = lambda *a: np.zeros(4800, np.float32)
    stt = FakeSTT(["one two three"], ready=False)
    d, ev, logs = make("in", stt, lambda t, s, g, c: "[EN] " + t, {"in_voice": False})
    for _ in range(6):                     # six sentences arrive while the model is still loading
        d.work.put((time.time(), tone(0.5)))
    threading.Thread(target=d._work_loop, daemon=True).start()
    time.sleep(0.5)
    assert not [e for e in ev if e["type"] == "caption"]       # waiting, not dropped
    stt._ready = True
    time.sleep(0.8)
    caps = [e for e in ev if e["type"] == "caption"]
    assert len(caps) == 1 and stt.calls == 1 and any("joined" in m for m in logs)   # all six merged into one


def test_echo_filters():
    d, ev, logs = make("in", FakeSTT(["Good morning everyone"]), lambda t, s, g, c: t)
    d.echo.add("said_in", "Good morning everyone")
    d._process(time.time(), tone(1.0))
    assert not [e for e in ev if e["type"] == "caption"]       # our own read-aloud voice is ignored
    d2, ev2, logs2 = make("out", FakeSTT(["can you see my screen"]), lambda t, s, g, c: t)
    d2.echo.add("heard_in", "Can you see my screen?")
    d2._process(time.time(), tone(1.0))
    assert not d2.output.clips and any("picked up the meeting" in m for m in logs2)
    d3, ev3, logs3 = make("out", FakeSTT(["can you see my screen"]), lambda t, s, g, c: t, {"out_headphones": True})
    d3.echo.add("heard_in", "Can you see my screen?")
    tts.synthesize = lambda *a: np.zeros(4800, np.float32)
    d3._process(time.time(), tone(1.0))
    assert d3.output.clips                                     # with headphones, nothing is filtered


def test_language_smoothing_uses_recent_confident_language():
    d, ev, logs = make("in", FakeSTT([]), lambda *a: "x")
    for _ in range(3):
        d._smooth_lang("ms", 0.9, "auto")
    assert d._smooth_lang("id", 0.3, "auto") == "ms"           # unsure Indonesian guess -> recent Malay
    assert d._smooth_lang("id", 0.95, "auto") == "id"
    assert d._smooth_lang("id", 0.3, "ta") == "ta"             # a fixed language always wins
