"""Speech recognition with Whisper running locally (faster-whisper). Free and offline.

The model downloads once (tiny 75 MB ... large-v3 3 GB) the first time it is used.
"""
import threading

from . import languages

# Phrases Whisper tends to "hear" in silence or music
HALLUCINATIONS = {
    "thank you.", "thanks for watching!", "thank you for watching.", "thank you for watching!",
    "please subscribe.", "subtitles by the amara.org community", "you", ".", "bye.",
    "terima kasih.", "字幕由amara.org社区提供", "ご視聴ありがとうございました",
}


class STT:
    def __init__(self, model_size, log):
        self.model_size = model_size
        self.log = log
        self.model = None
        self.lock = threading.Lock()
        self.load_error = None

    def load(self):
        with self.lock:
            if self.model is not None:
                return True
            try:
                from faster_whisper import WhisperModel
                device, compute = "cpu", "int8"
                try:
                    import ctranslate2
                    if ctranslate2.get_cuda_device_count() > 0:
                        device, compute = "cuda", "float16"
                except Exception:
                    pass
                self.log(f"Loading speech model '{self.model_size}' on {device.upper()} "
                         f"(first time downloads it, please wait)...")
                self.model = WhisperModel(self.model_size, device=device, compute_type=compute)
                self.log("Speech model ready.")
                return True
            except Exception as e:
                self.load_error = e
                self.log(f"Could not load the speech model: {e}")
                return False

    def transcribe(self, audio16k, lang_hint=None, prompt=None):
        """Returns (text, language_code, probability). language_code uses LINGUA codes."""
        if self.model is None and not self.load():
            return "", None, 0.0
        with self.lock:
            segments, info = self.model.transcribe(
                audio16k,
                language=languages.to_whisper(lang_hint),
                beam_size=1,
                vad_filter=True,
                vad_parameters={"min_silence_duration_ms": 400},
                condition_on_previous_text=False,
                initial_prompt=prompt or None,
            )
            parts = []
            for s in segments:
                if s.no_speech_prob > 0.6 and s.avg_logprob < -1.0:
                    continue
                parts.append(s.text)
        text = "".join(parts).strip()
        if text.lower() in HALLUCINATIONS or len(text) < 2:
            return "", None, 0.0
        return text, languages.from_whisper(info.language), float(info.language_probability or 0)
