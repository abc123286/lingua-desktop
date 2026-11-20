"""Splits a live audio stream into sentences (speech segments) using energy with an adaptive noise floor."""
import collections

import numpy as np

SR = 16000
BLOCK_MS = 50


class Segmenter:
    def __init__(self, sensitivity=3.0, silence_ms=700, max_seconds=12.0, min_speech_ms=350, preroll_ms=300):
        self.sensitivity = sensitivity
        self.silence_blocks = max(2, int(silence_ms / BLOCK_MS))
        self.max_samples = int(max_seconds * SR)
        self.min_speech_blocks = max(1, int(min_speech_ms / BLOCK_MS))
        self.preroll = collections.deque(maxlen=max(1, int(preroll_ms / BLOCK_MS)))
        self.noise = 0.003
        self.buf = []
        self.in_speech = False
        self.silent = 0
        self.voiced = 0

    @property
    def speaking(self):
        return self.in_speech

    def feed(self, block):
        """block: float32 mono 16 kHz (~50 ms). Returns a finished segment (np.ndarray) or None."""
        rms = float(np.sqrt(np.mean(block * block) + 1e-12))
        threshold = max(0.006, self.noise * self.sensitivity)
        is_voice = rms > threshold
        if not self.in_speech:
            # learn background noise only while nobody is talking
            self.noise = 0.95 * self.noise + 0.05 * min(rms, 0.05)
            self.preroll.append(block)
            if is_voice:
                self.in_speech = True
                self.buf = list(self.preroll)
                self.silent = 0
                self.voiced = 1
            return None
        self.buf.append(block)
        if is_voice:
            self.voiced += 1
            self.silent = 0
        else:
            self.silent += 1
        total = sum(len(b) for b in self.buf)
        if self.silent >= self.silence_blocks or total >= self.max_samples:
            return self._finish(force_keep=total >= self.max_samples)
        return None

    def _finish(self, force_keep=False):
        seg = np.concatenate(self.buf) if self.buf else None
        voiced = self.voiced
        self.buf, self.in_speech, self.silent, self.voiced = [], False, 0, 0
        self.preroll.clear()
        if seg is None or (voiced < self.min_speech_blocks and not force_keep):
            return None
        return seg

    def flush(self):
        return self._finish() if self.in_speech else None
