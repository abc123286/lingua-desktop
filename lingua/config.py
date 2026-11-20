"""Settings saved in the user's home folder (~/.lingua_desktop/config.json)."""
import json
import os
from pathlib import Path

HOME = Path(os.path.expanduser("~")) / ".lingua_desktop"
CONFIG_FILE = HOME / "config.json"
TRANSCRIPTS = HOME / "transcripts"

DEFAULTS = {
    # --- Hear others (meeting audio -> me) ---
    "in_source": "",            # loopback / BlackHole input name ("" = auto)
    "in_lang": "en",            # language I want to read / hear
    "in_speaker_lang": "auto",  # language the meeting speaks ("auto" = detect)
    "in_voice": False,          # read translations aloud (captions are always on)
    "in_voice_output": "",      # where to play it ("" = default speakers)
    "in_gender": "Female",
    # --- Translate my voice (me -> meeting) ---
    "out_mic": "",              # my real microphone ("" = default)
    "out_virtual": "",          # virtual cable / BlackHole output that Zoom uses as its mic
    "out_my_lang": "auto",      # language I speak ("auto" = detect)
    "out_lang": "en",           # language the meeting should hear
    "out_gender": "Female",
    "out_passthrough": True,    # when translation is OFF, send my normal voice through
    # --- Engines ---
    "whisper_model": "base",    # tiny / base / small / medium / large-v3
    "translator": "google_free",  # google_free / gemini
    "gemini_key": "",
    "gemini_model": "gemini-flash-latest",
    "glossary": "",
    "rate": 1.0,
    "sensitivity": 3.0,         # higher = needs louder speech to trigger
    "silence_ms": 500,          # pause that ends a sentence
    "max_seconds": 6,           # longest piece of continuous talk before translating
    # --- Overlay ---
    "overlay_font": 20,
    "overlay_alpha": 0.85,
    "overlay_show_original": True,
    "overlay_x": -1,
    "overlay_y": -1,
    "overlay_width": 900,
    "save_transcript": False,
}


def load():
    cfg = dict(DEFAULTS)
    try:
        cfg.update(json.loads(CONFIG_FILE.read_text(encoding="utf-8")))
    except Exception:
        pass
    return cfg


def save(cfg):
    try:
        HOME.mkdir(parents=True, exist_ok=True)
        CONFIG_FILE.write_text(json.dumps(cfg, indent=2, ensure_ascii=False), encoding="utf-8")
    except Exception as e:  # never crash on save
        print("Could not save settings:", e)
