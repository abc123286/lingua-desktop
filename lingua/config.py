"""Settings in the user's home folder (~/.lingua_desktop/config.json).

API keys are NOT stored in that file: they go to the operating system's keychain
(Windows Credential Manager / macOS Keychain) through the `keyring` package. Only if no keychain
is available are they kept in a separate file readable only by you.
"""
import json
import os
import stat
import threading
import time
from pathlib import Path

HOME = Path(os.path.expanduser("~")) / ".lingua_desktop"
CONFIG_FILE = HOME / "config.json"
SECRETS_FILE = HOME / "secrets.json"
TRANSCRIPTS = HOME / "transcripts"
SERVICE = "LINGUA Desktop"
SECRET_KEYS = ("gemini_key", "groq_key")

DEFAULTS = {
    # --- Hear others (meeting audio -> me) ---
    "in_source": "",
    "in_lang": "en",
    "in_speaker_lang": "auto",
    "in_voice": False,
    "in_voice_output": "",
    "in_gender": "Female",
    # --- Translate my voice (me -> meeting) ---
    "out_mic": "",
    "out_virtual": "",
    "out_my_lang": "auto",
    "out_lang": "en",
    "out_gender": "Female",
    "out_passthrough": True,
    "out_headphones": False,
    # --- Engines ---
    "stt_engine": "local",       # local / groq
    "whisper_model": "base",     # tiny / base / small / medium / large-v3
    "translator": "google_free", # google_free / gemini
    "gemini_model": "gemini-flash-latest",
    "glossary": "",
    "rate": 1.0,
    "sensitivity": 3.0,
    "silence_ms": 500,
    "max_seconds": 6,
    "live_captions": True,
    # --- Overlay ---
    "overlay_font": 20,
    "overlay_alpha": 0.85,
    "overlay_show_original": True,
    "overlay_lines": 3,
    "overlay_clickthrough": False,
    "overlay_x": -1,
    "overlay_y": -1,
    "overlay_width": 900,
    # --- Privacy & keys ---
    "save_transcript": False,
    "transcript_days": 30,
    "privacy_ack": False,
    "hotkeys_enabled": False,
    "hotkey_in": "<ctrl>+<alt>+h",
    "hotkey_out": "<ctrl>+<alt>+m",
    "hotkey_overlay": "<ctrl>+<alt>+o",
}


def _private(path):
    try:
        if os.name != "nt":
            os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)
    except Exception:
        pass


def load():
    cfg = dict(DEFAULTS)
    try:
        cfg.update(json.loads(CONFIG_FILE.read_text(encoding="utf-8")))
    except Exception:
        pass
    # move keys saved by older versions out of the plain settings file
    moved = False
    for k in SECRET_KEYS:
        if cfg.get(k):
            set_secret(k, cfg[k])
            moved = True
        cfg.pop(k, None)
    if moved:
        _write(cfg)
    return cfg


def _write(cfg):
    try:
        HOME.mkdir(parents=True, exist_ok=True)
        data = {k: v for k, v in cfg.items() if k not in SECRET_KEYS}
        CONFIG_FILE.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        _private(CONFIG_FILE)
    except Exception as e:
        print("Could not save settings:", e)


_timer = None
_timer_lock = threading.Lock()


def save(cfg, delay=0.8):
    """Saves after changes stop for a moment (dragging a slider no longer writes the file on every tick)."""
    global _timer
    with _timer_lock:
        if _timer:
            _timer.cancel()
        if delay <= 0:
            _timer = None
            _write(cfg)
            return
        _timer = threading.Timer(delay, _write, args=(cfg,))
        _timer.daemon = True
        _timer.start()


# ---------------- secrets ----------------
def _keyring():
    try:
        import keyring
        keyring.get_keyring()
        return keyring
    except Exception:
        return None


def get_secret(name):
    kr = _keyring()
    if kr:
        try:
            v = kr.get_password(SERVICE, name)
            if v:
                return v
        except Exception:
            pass
    try:
        return json.loads(SECRETS_FILE.read_text(encoding="utf-8")).get(name, "")
    except Exception:
        return ""


def set_secret(name, value):
    value = (value or "").strip()
    kr = _keyring()
    if kr:
        try:
            if value:
                kr.set_password(SERVICE, name, value)
            else:
                try:
                    kr.delete_password(SERVICE, name)
                except Exception:
                    pass
            return "keychain"
        except Exception:
            pass
    try:
        HOME.mkdir(parents=True, exist_ok=True)
        data = {}
        try:
            data = json.loads(SECRETS_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
        if value:
            data[name] = value
        else:
            data.pop(name, None)
        SECRETS_FILE.write_text(json.dumps(data), encoding="utf-8")
        _private(SECRETS_FILE)
        return "file"
    except Exception:
        return "none"


def cleanup_transcripts(days):
    """Delete transcript files older than `days` (0 = keep forever)."""
    if not days or days <= 0 or not TRANSCRIPTS.exists():
        return 0
    cutoff, n = time.time() - days * 86400, 0
    for f in TRANSCRIPTS.glob("*.txt"):
        try:
            if f.stat().st_mtime < cutoff:
                f.unlink()
                n += 1
        except Exception:
            pass
    return n
