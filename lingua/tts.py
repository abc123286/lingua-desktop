"""Text-to-speech with Microsoft Edge's free neural voices (edge-tts). No key needed; needs internet.
400+ voices in 100+ languages, e.g. ms-MY, ta-MY, zh-CN, zh-HK (Cantonese), th-TH, km-KH, my-MM, lo-LA.
"""
import asyncio
import threading

import numpy as np

from . import languages

_voices = None
_voices_lock = threading.Lock()


def _all_voices():
    global _voices
    with _voices_lock:
        if _voices is None:
            import edge_tts
            _voices = asyncio.run(edge_tts.list_voices())
        return _voices


def pick_voice(code, gender="Female"):
    locale = languages.tts_locale(code)
    base = locale.split("-")[0].lower()
    voices = _all_voices()
    exact = [v for v in voices if v.get("Locale", "").lower() == locale.lower()]
    same_lang = [v for v in voices if v.get("Locale", "").lower().split("-")[0] == base]
    for pool in (exact, same_lang):
        if pool:
            for v in pool:
                if v.get("Gender") == gender:
                    return v["ShortName"]
            return pool[0]["ShortName"]
    return None


def has_voice(code):
    try:
        return pick_voice(code) is not None
    except Exception:
        return False


async def _synth(text, voice, rate):
    import edge_tts
    pct = int(round((rate - 1.0) * 100))
    com = edge_tts.Communicate(text, voice, rate=f"{pct:+d}%")
    buf = bytearray()

    async def run():
        async for chunk in com.stream():
            if chunk.get("type") == "audio":
                buf.extend(chunk["data"])
    await asyncio.wait_for(run(), timeout=8)
    return bytes(buf)


def split_clauses(text, max_len=120):
    """Speak long translations piece by piece. The first piece is kept short so the voice starts sooner."""
    import re
    parts = [p.strip() for p in re.split(r"(?<=[.!?;:,。！？；：，、])\s*", text) if p.strip()]
    out, cur = [], ""
    for p in parts:
        cjk = languages.is_cjk_char(p)
        joined = (cur + p) if cjk else (cur + " " + p).strip()
        if cur and len(joined) > max_len:
            out.append(cur)
            joined = p
        cur = joined
        first = not out
        min_len = (6 if cjk else 12) if first else (10 if cjk else 25)
        ends = cur[-1:] in (".!?;:,。！？；：，、" if first else ".!?;:。！？；：")
        if (len(cur) >= min_len and ends) or len(cur) >= 70:
            out.append(cur)
            cur = ""
    if cur:
        out.append(cur)
    return out or [text]


def synthesize(text, code, gender="Female", rate=1.0, sample_rate=48000):
    """Returns float32 mono audio at sample_rate, or None if no voice exists for the language."""
    voice = pick_voice(code, gender)
    if not voice:
        return None
    rate = max(0.5, min(2.0, rate))
    mp3 = asyncio.run(_synth(text[:2000], voice, rate))
    if not mp3:
        return None
    import miniaudio
    dec = miniaudio.decode(mp3, output_format=miniaudio.SampleFormat.FLOAT32, nchannels=1, sample_rate=sample_rate)
    return np.asarray(dec.samples, dtype=np.float32)
