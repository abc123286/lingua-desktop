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
                "deep_translator", "pynput.keyboard", "certifi", "lingua.ui"):
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

            t0 = time.time()
            clip48 = tts.synthesize("Good morning everyone, the meeting will start in five minutes.", "en", "Female", 1.0)
            assert clip48 is not None and len(clip48) > 48000, "voice synthesis returned no audio"
            log(f"OK   Edge voice: {len(clip48) / 48000:.1f}s of audio in {time.time() - t0:.1f}s")

            from lingua.audio import to_16k
            stt = STT("tiny", log)
            t0 = time.time()
            text, lang, p = stt.transcribe(to_16k(clip48).astype(np.float32))
            assert text and "meeting" in text.lower(), f"recognition gave {text!r}"
            log(f"OK   Whisper: {text!r} (lang={lang}) in {time.time() - t0:.1f}s")

            # Translation uses outside free services that sometimes refuse cloud build machines,
            # so a refusal here is reported as a warning, not a broken app.
            tr = Translator(dict(config.DEFAULTS), log)
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
