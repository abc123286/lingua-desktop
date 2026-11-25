"""Audio devices: capture (microphone or meeting audio) and playback (speakers or virtual mic).

Uses the `soundcard` library (WASAPI on Windows, CoreAudio on macOS).
- Windows: meeting audio is captured with WASAPI "loopback" of your speakers. No extra driver needed.
- macOS: macOS cannot record its own output, so meeting audio comes in through the free BlackHole driver.
- Virtual mic: we play the translated voice into "CABLE Input" (VB-Cable, Windows) or
  "BlackHole 16ch" (macOS). In Zoom/Teams/Meet you pick the matching device as your microphone.
"""
import queue
import sys
import threading
import time

import numpy as np

DEV_SR = 48000          # device sample rate
SR = 16000              # speech recognition sample rate
BLOCK = DEV_SR // 20    # 50 ms


def _com_init():
    """soundcard on Windows needs COM in every thread that touches audio."""
    if sys.platform == "win32":
        try:
            import ctypes
            ctypes.windll.ole32.CoInitializeEx(None, 0x0)  # COINIT_MULTITHREADED
        except Exception:
            pass


def _sc():
    import soundcard as sc  # imported lazily so the UI can show a clear error
    return sc


def list_microphones():
    sc = _sc()
    return [m.name for m in sc.all_microphones(include_loopback=False)]


def list_meeting_sources():
    """Devices that carry the meeting's sound.
    Windows: loopback of each speaker. macOS: inputs such as BlackHole 2ch."""
    sc = _sc()
    out = []
    for m in sc.all_microphones(include_loopback=True):
        if getattr(m, "isloopback", False):
            out.append(m.name)
    if not out:  # macOS (or no loopback support): offer inputs, virtual ones first
        mics = [m.name for m in sc.all_microphones(include_loopback=False)]
        out = sorted(mics, key=lambda n: 0 if "blackhole" in n.lower() else 1)
    return out


def list_speakers():
    sc = _sc()
    return [s.name for s in sc.all_speakers()]


def guess_virtual_output():
    """Find VB-Cable / BlackHole automatically."""
    try:
        names = list_speakers()
    except Exception:
        return ""
    for key in ("cable input", "blackhole 16ch", "blackhole", "vb-audio", "virtual"):
        for n in names:
            if key in n.lower():
                return n
    return ""


def guess_meeting_source():
    try:
        names = list_meeting_sources()
    except Exception:
        return ""
    if not names:
        return ""
    if sys.platform == "win32":
        try:
            default = _sc().default_speaker().name
            for n in names:
                if n == default:
                    return n
        except Exception:
            pass
    for n in names:
        if "blackhole 2ch" in n.lower():
            return n
    return names[0]


def find_mic(name, loopback=False):
    sc = _sc()
    mics = sc.all_microphones(include_loopback=loopback)
    if name:
        for m in mics:
            if m.name == name:
                return m
    if loopback and sys.platform == "win32":
        default = sc.default_speaker().name
        for m in mics:
            if getattr(m, "isloopback", False) and m.name == default:
                return m
    return sc.default_microphone()


def find_speaker(name):
    sc = _sc()
    if name:
        for s in sc.all_speakers():
            if s.name == name:
                return s
    return sc.default_speaker()


def _lowpass_taps(n=31, cutoff=0.30):
    """Windowed-sinc low-pass filter (cutoff as a fraction of the 48 kHz sample rate's Nyquist band)."""
    m = np.arange(n) - (n - 1) / 2
    h = np.sinc(2 * cutoff * m / 2) * np.hamming(n)
    return (h / h.sum()).astype(np.float32)


_TAPS = _lowpass_taps()


class Resampler:
    """48 kHz -> 16 kHz with a proper anti-aliasing filter, continuous across blocks."""

    def __init__(self):
        self.tail = np.zeros(len(_TAPS) - 1, dtype=np.float32)
        self.phase = 0

    def __call__(self, block48):
        x = np.concatenate([self.tail, block48.astype(np.float32)])
        y = np.convolve(x, _TAPS, mode="valid")
        self.tail = x[-(len(_TAPS) - 1):]
        out = y[self.phase::3]
        self.phase = (self.phase - len(y)) % 3
        return out.astype(np.float32)


def to_16k(block48):
    """Stateless helper (tests and one-off clips)."""
    return Resampler()(block48)


def to_48k(audio16k):
    """16 kHz -> 48 kHz for playing a recorded sentence back into the meeting."""
    n = len(audio16k)
    if n == 0:
        return audio16k
    return np.interp(np.arange(n * 3) / 3.0, np.arange(n), audio16k).astype(np.float32)


class Capture(threading.Thread):
    """Reads a device continuously and calls on_block(mono_float32_48k)."""

    def __init__(self, device, on_block, on_error):
        super().__init__(daemon=True)
        self.device, self.on_block, self.on_error = device, on_block, on_error
        self.stop_evt = threading.Event()

    def run(self):
        _com_init()
        try:
            with self.device.recorder(samplerate=DEV_SR, blocksize=BLOCK) as rec:
                while not self.stop_evt.is_set():
                    data = rec.record(numframes=BLOCK)
                    if data is None or len(data) == 0:
                        continue
                    mono = data.mean(axis=1) if data.ndim > 1 else data
                    self.on_block(np.asarray(mono, dtype=np.float32))
        except Exception as e:
            if not self.stop_evt.is_set():
                self.on_error(e)

    def stop(self):
        self.stop_evt.set()


class Output(threading.Thread):
    """Plays float32 mono 48 kHz audio on a device from a queue. Clips can be skipped."""

    def __init__(self, device, on_error, volume=1.0):
        super().__init__(daemon=True)
        self.device, self.on_error, self.volume = device, on_error, volume
        self.q = queue.Queue()
        self.stop_evt = threading.Event()
        self.skip_evt = threading.Event()
        self.busy = False          # True while a voice clip is playing
        self.last_voice = 0.0      # time the last voice clip finished

    def play_clip(self, audio, on_start=None):
        self.q.put(("clip", (audio, on_start) if on_start else audio))

    def stream(self, block):
        """Pass-through audio (e.g. your normal voice). Dropped while a clip is playing."""
        if not self.busy and self.q.qsize() < 10:
            self.q.put(("stream", block))

    def skip(self):
        self.skip_evt.set()
        with self.q.mutex:
            self.q.queue.clear()

    def backlog(self):
        """Number of clips waiting (used to speed up speech when it falls behind)."""
        with self.q.mutex:
            return sum(1 for k, _ in self.q.queue if k == "clip")

    def skip_to_latest(self):
        with self.q.mutex:
            clips = [x for x in self.q.queue if x[0] == "clip"]
            self.q.queue.clear()
            if clips:
                self.q.queue.append(clips[-1])
        self.skip_evt.set()

    def run(self):
        _com_init()
        try:
            with self.device.player(samplerate=DEV_SR, channels=2, blocksize=BLOCK) as p:
                while not self.stop_evt.is_set():
                    try:
                        kind, audio = self.q.get(timeout=0.1)
                    except queue.Empty:
                        continue
                    if kind == "clip":
                        self.busy = True
                        self.skip_evt.clear()
                        if isinstance(audio, tuple):
                            audio, on_start = audio
                            try:
                                on_start()
                            except Exception:
                                pass
                        for i in range(0, len(audio), BLOCK):
                            if self.stop_evt.is_set() or self.skip_evt.is_set():
                                break
                            chunk = audio[i:i + BLOCK] * self.volume
                            p.play(np.column_stack([chunk, chunk]))
                        self.busy = False
                        self.last_voice = time.time()
                    else:
                        p.play(np.column_stack([audio, audio]))
        except Exception as e:
            self.busy = False
            if not self.stop_evt.is_set():
                self.on_error(e)

    def stop(self):
        self.stop_evt.set()
        self.skip_evt.set()
