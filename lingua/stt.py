"""Speech recognition.

Two engines:
- "local": Whisper on this computer (faster-whisper). Free, offline. Speed depends on the computer.
- "groq":  Whisper large-v3-turbo on Groq's servers. Free key from console.groq.com. Much faster
           (typically 0.3-0.8 s per sentence), but the free tier allows about 20 requests a minute,
           so it is used for finished sentences; live captions stay local.
"""
import io
import json
import threading
import time
import urllib.error
import urllib.request
import uuid
import wave

import numpy as np

from . import languages

# Text Whisper produces from silence or music. Only clear junk is listed: everyday replies such as
# "Thank you", "Bye" or "Terima kasih" are real speech and are kept.
HALLUCINATIONS = {
    "thanks for watching!", "thanks for watching.", "thank you for watching.", "thank you for watching!",
    "please subscribe.", "please subscribe to my channel.", "subtitles by the amara.org community",
    "字幕由amara.org社区提供", "ご視聴ありがとうございました", "구독과 좋아요 부탁드립니다",
}


def is_junk(text):
    t = text.strip()
    if not t:
        return True
    if t.lower() in HALLUCINATIONS:
        return True
    # one CJK character (好, 是, 对, 係) is a real answer; a lone Latin letter or symbol is noise
    if len(t) == 1 and not languages.is_cjk_char(t):
        return True
    return False


class LocalSTT:
    name = "local"

    def __init__(self, model_size, log, status):
        self.model_size, self.log, self.status = model_size, log, status
        self.model = None
        self.device = "cpu"
        self.lock = threading.Lock()
        self.loading = False

    def ready(self):
        return self.model is not None

    def load(self):
        with self.lock:
            if self.model is not None:
                return True
            self.loading = True
            self.status("loading", f"Loading speech model '{self.model_size}' (the first time it downloads; this can take minutes)…")
            try:
                from faster_whisper import WhisperModel
                want_gpu = False
                try:
                    import ctranslate2
                    want_gpu = ctranslate2.get_cuda_device_count() > 0
                except Exception:
                    pass
                model = None
                if want_gpu:
                    try:
                        model = WhisperModel(self.model_size, device="cuda", compute_type="float16")
                        model.transcribe(np.zeros(16000, dtype=np.float32), beam_size=1)  # prove CUDA really works
                        self.device = "cuda"
                    except Exception as e:
                        self.log(f"Graphics card not usable ({e}); using the processor instead.")
                        model = None
                if model is None:
                    model = WhisperModel(self.model_size, device="cpu", compute_type="int8")
                    self.device = "cpu"
                self.model = model
                self.status("ready", f"Speech model '{self.model_size}' ready on {self.device.upper()}.")
                return True
            except Exception as e:
                self.status("error", f"Could not load the speech model: {e}")
                return False
            finally:
                self.loading = False

    def transcribe(self, audio16k, lang_hint=None, prompt=None, quick=False):
        """Returns (text, language_code, probability)."""
        if self.model is None and not self.load():
            return "", None, 0.0
        whisper_lang = languages.to_whisper(lang_hint, self.model_size)
        if quick and not self.lock.acquire(blocking=False):
            return None, None, 0.0          # busy with a finished sentence: skip this live preview
        if not quick:
            self.lock.acquire()
        try:
            kwargs = dict(language=whisper_lang, beam_size=1, condition_on_previous_text=False,
                          initial_prompt=prompt or None, vad_filter=not quick,
                          vad_parameters={"min_silence_duration_ms": 300} if not quick else None)
            if whisper_lang is None:
                kwargs["multilingual"] = True   # lets Malay/English mixed in one sentence come out as spoken
            kwargs = {k: v for k, v in kwargs.items() if v is not None or k in ("language", "initial_prompt")}
            try:
                segments, info = self.model.transcribe(audio16k, **kwargs)
            except TypeError:                   # older faster-whisper without 'multilingual'
                kwargs.pop("multilingual", None)
                segments, info = self.model.transcribe(audio16k, **kwargs)
            parts = [s.text for s in segments if not (s.no_speech_prob > 0.6 and s.avg_logprob < -1.0)]
        finally:
            self.lock.release()
        text = "".join(parts).strip()
        if is_junk(text):
            return "", None, 0.0
        return text, languages.from_whisper(info.language), float(info.language_probability or 0)


def _wav_bytes(audio16k):
    pcm = np.clip(audio16k, -1, 1)
    pcm = (pcm * 32767).astype("<i2").tobytes()
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(16000)
        w.writeframes(pcm)
    return buf.getvalue()


class GroqSTT:
    name = "groq"
    URL = "https://api.groq.com/openai/v1/audio/transcriptions"

    def __init__(self, key_getter, log, status):
        self.key_getter, self.log, self.status = key_getter, log, status
        self.cooldown_until = 0
        self.lock = threading.Lock()

    def ready(self):
        return bool(self.key_getter())

    def load(self):
        ok = self.ready()
        self.status("ready" if ok else "error", "Fast cloud speech (Groq) ready." if ok else "Add your free Groq key in AI engines.")
        return ok

    def transcribe(self, audio16k, lang_hint=None, prompt=None, quick=False):
        if quick:
            return None, None, 0.0            # free tier: ~20 requests/minute, keep it for finished sentences
        key = self.key_getter()
        if not key:
            raise RuntimeError("No Groq key")
        if time.time() < self.cooldown_until:
            raise RuntimeError("Groq rate limit")
        boundary = uuid.uuid4().hex
        fields = {"model": "whisper-large-v3-turbo", "response_format": "verbose_json", "temperature": "0"}
        wl = languages.to_whisper(lang_hint, "large-v3")
        if wl:
            fields["language"] = wl
        if prompt:
            fields["prompt"] = prompt[:400]
        body = io.BytesIO()
        for k, v in fields.items():
            body.write(f"--{boundary}\r\nContent-Disposition: form-data; name=\"{k}\"\r\n\r\n{v}\r\n".encode())
        body.write(f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"a.wav\"\r\nContent-Type: audio/wav\r\n\r\n".encode())
        body.write(_wav_bytes(audio16k))
        body.write(f"\r\n--{boundary}--\r\n".encode())
        req = urllib.request.Request(self.URL, data=body.getvalue(), headers={
            "Authorization": "Bearer " + key, "Content-Type": "multipart/form-data; boundary=" + boundary})
        from .translate import ssl_ctx
        try:
            with urllib.request.urlopen(req, timeout=6, context=ssl_ctx()) as r:
                data = json.loads(r.read().decode())
        except urllib.error.HTTPError as e:
            if e.code == 429:
                self.cooldown_until = time.time() + 20
            raise RuntimeError(f"Groq HTTP {e.code}")
        text = (data.get("text") or "").strip()
        if is_junk(text):
            return "", None, 0.0
        lang = languages.whisper_name_to_code(data.get("language") or "") or lang_hint
        return text, lang, 0.9 if lang else 0.0


class STT:
    """Chooses the engine; falls back to local Whisper if the cloud call fails."""

    def __init__(self, cfg, log, status, key_getter):
        self.cfg, self.log, self._status = cfg, log, status
        self.local = LocalSTT(cfg["whisper_model"], log, status)
        self.groq = GroqSTT(key_getter, log, status)
        self.state = "idle"

    def status(self, state, msg):
        self.state = state
        self._status(state, msg)

    @property
    def engine(self):
        return self.groq if self.cfg.get("stt_engine") == "groq" and self.groq.ready() else self.local

    def set_model(self, size):
        with self.local.lock:
            self.local.model, self.local.model_size = None, size

    def ready(self):
        return self.engine.ready()

    def load(self):
        if self.engine is self.groq:
            self.groq.load()
            threading.Thread(target=self.local.load, daemon=True).start()  # for live captions and fallback
            return True
        return self.local.load()

    def transcribe(self, audio16k, lang_hint=None, prompt=None, quick=False):
        eng = self.engine
        if quick:
            return self.local.transcribe(audio16k, lang_hint, prompt, quick=True) if self.local.ready() else (None, None, 0.0)
        if eng is self.groq:
            try:
                return self.groq.transcribe(audio16k, lang_hint, prompt)
            except Exception as e:
                self.log(f"Cloud speech failed ({e}); using this computer for this sentence.")
        return self.local.transcribe(audio16k, lang_hint, prompt)
