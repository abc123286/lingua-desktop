"""Checks the packaged app really contains working parts. Used by the GitHub build.

  LINGUA --selftest          imports every component
  LINGUA --selftest --full   also: Edge voice -> Whisper recognition -> Google translation (needs internet)
"""
import os
import sys
import time
import traceback


def _say(msg):
    print(msg, flush=True)


def run(full=False):
    out = os.environ.get("LINGUA_SELFTEST_OUT")
    lines = []

    def log(m):
        lines.append(m)
        _say(m)

    ok = True
    for mod in ("tkinter", "numpy", "soundcard", "faster_whisper", "ctranslate2", "edge_tts", "miniaudio",
                "keyring", "pynput.keyboard", "certifi", "lingua.ui"):
        try:
            __import__(mod)
            log(f"OK   import {mod}")
        except Exception as e:
            ok = False
            log(f"FAIL import {mod}: {e!r}")

    if ok and full:
        try:
            import numpy as np
            from lingua import tts
            from lingua.stt import STT
            from lingua.translate import Translator
            from lingua import config

            # 1) speech recognition on this machine must work (hard requirement)
            sr, t = 16000, None
            cfg = dict(config.DEFAULTS, whisper_model="tiny")
            stt = STT(cfg, log, lambda st, m: log("     " + m), key_getter=lambda: "")
            # 2) voice service (network) - a refusal is a warning, like translation
            clip48 = None
            try:
                t0 = time.time()
                clip48 = tts.synthesize("Good morning everyone, the meeting will start in five minutes.", "en", "Female", 1.0)
                assert clip48 is not None and len(clip48) > 48000
                log(f"OK   Edge voice: {len(clip48) / 48000:.1f}s of audio in {time.time() - t0:.1f}s")
            except Exception as e:
                log(f"WARN voice service refused this build machine: {e!r}")
            from lingua.audio import to_16k
            audio16 = to_16k(clip48) if clip48 is not None else np.zeros(sr, dtype=np.float32)
            t0 = time.time()
            assert stt.load(), "speech model did not load"
            text, lang, p = stt.transcribe(audio16.astype(np.float32))
            if clip48 is not None:
                assert text and "meeting" in text.lower(), f"recognition gave {text!r}"
                log(f"OK   Whisper: {text!r} (lang={lang}, p={p:.2f}) in {time.time() - t0:.1f}s")
            else:
                log("OK   Whisper model loads and runs (no voice sample to recognise)")
            text = text or "Good morning everyone, the meeting will start in five minutes."
            tr = Translator(cfg, log, key_getter=lambda: "")
            t0 = time.time()
            try:
                ms = tr.translate(text, lang or "en", "ms")
                assert ms and ms.strip().lower() != text.strip().lower(), f"translation gave {ms!r}"
                log(f"OK   translate → Malay: {ms!r} in {time.time() - t0:.1f}s")
            except Exception as e:
                log(f"WARN translation services refused this build machine: {e}")
        except Exception as e:
            ok = False
            log(f"FAIL pipeline: {e!r}")
            log(traceback.format_exc())

    log("SELFTEST PASSED" if ok else "SELFTEST FAILED")
    if out:
        with open(out, "w", encoding="utf-8") as f:
            f.write("\n".join(lines))
    return 0 if ok else 1
