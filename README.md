# LINGUA Desktop: live translation for any meeting app

LINGUA Desktop runs **beside** Zoom, Microsoft Teams, Google Meet, Webex, WhatsApp/Telegram desktop calls, or even a YouTube video. You switch it on and off whenever you like.

| Switch | What it does |
|---|---|
| 🎧 **Hear others in my language** | Listens to the sound your computer plays and shows translated captions in a floating bar on top of every window. A live caption refreshes about every second while someone talks. It can also read the translations aloud. |
| 🎙 **Others hear me in their language** | You speak normally; the meeting hears a translated AI voice through a "virtual microphone". If a translation or the voice ever fails, your own recorded words are sent instead, so the meeting never hears silence. When this switch is OFF, your normal voice passes through. |

## Download
- **Ready-made app** (no Python needed): https://github.com/abc123286/lingua-desktop/releases/latest
  - Windows 10/11: `LINGUA-Windows.zip` → unzip → `LINGUA.exe`. The app isn't code-signed, so Windows SmartScreen and some antivirus tools warn: **More info → Run anyway**.
  - Mac with Apple Silicon (M1–M4): `LINGUA-Mac-AppleSilicon.zip` → drag to Applications → right-click → **Open** the first time. It is ad-hoc signed, not notarised by Apple. Intel Macs: use the Python version below.
- **Python version** (any computer): install **Python 3.12** from python.org, then double-click `1_INSTALL_Windows.bat` / `1_INSTALL_Mac.command`, then `2_START_…`.

## Speed — what to expect
LINGUA shows its real measured delays in the **Speed** box (typical, and slowest 5%).

| Setup | Live caption while someone talks | Finished sentence |
|---|---|---|
| **local**, `base` model, typical laptop | about 1–2 s behind | about 2–4 s after they pause |
| **local**, `tiny` model | about 1 s behind (less accurate) | about 1.5–3 s |
| **groq** for sentences (free key) + local `tiny` for live captions | about 1 s behind | about 1–2 s |

Live captions always run on your computer (the free Groq plan allows only about 20 requests a minute), so on a slow laptop they lag more. The Speed box shows your real numbers.

No translator can be truly instant: it has to hear words before it can translate them (and some languages put the verb at the end), and the translated **voice** always comes after the caption, usually 1–3 s after the sentence ends. Live captions are a first draft that the finished sentence then replaces.

**Fastest setup:** AI engines → Speech recognition = **groq** with a free key from https://console.groq.com (about 20 sentences a minute on the free plan; above that LINGUA uses your computer for that sentence) · Local speech model = **tiny** (used for live captions) · keep **Live captions** on · use headphones.

## Connect it to your meeting app (one time)
**Hear others** — Windows: nothing to set up; choose your speakers/headphones in *Meeting audio comes from*. LINGUA hears everything that device plays, so mute music and notifications. Mac: install **BlackHole 2ch** (https://existential.audio/blackhole/), create a *Multi-Output Device* in Audio MIDI Setup with your headphones + BlackHole 2ch, select it as Zoom's speaker, and choose BlackHole 2ch in LINGUA.

**Others hear me** — install the free virtual cable, then:

| | LINGUA → *Send voice to* | Zoom / Teams / Meet → **Microphone** |
|---|---|---|
| Windows (VB-Cable, https://vb-audio.com/Cable/) | CABLE Input | **CABLE Output** |
| Mac (BlackHole 16ch) | BlackHole 16ch | **BlackHole 16ch** (never add it to the Multi-Output Device) |

With *"When OFF, pass my normal voice"* ticked, your microphone stays on while LINGUA is open and sends your normal voice; the caption bar shows **"🎙 Mic → meeting"** whenever this happens. Turn off Zoom's noise suppression ("Original sound") for a clearer AI voice.

## Privacy (tell the people in your meeting)
- **Speech recognition:** on this computer (local) — or, if you choose **groq**, the audio of each sentence goes to Groq.
- **Translation:** the recognised **text** goes to Google Translate's free web service, to **MyMemory** when Google is busy, or to **Google Gemini** if you add a key. Check Google's current free-tier terms before using Gemini for confidential meetings: free-tier data may be used to improve their products.
- **Voice:** text that is read aloud goes to Microsoft's Edge voice service.
- **Everyone's speech** (not only yours) goes through these services. LINGUA shows this notice on first start and in its Privacy tab.
- **Storage:** no audio is saved. Text transcripts only if you turn them on (deleted after 30 days by default). API keys are stored in the system keychain (Windows Credential Manager / macOS Keychain), not in the settings file.
- **Keyboard shortcuts are off by default.** Turning them on makes LINGUA watch all key presses (to notice its shortcuts; nothing is stored). Some security tools warn about this.
- The free Google and Microsoft endpoints are **unofficial**: they can change or stop working, and their terms may not allow business use.

## Tips
- **Speech model** (local): `base` is the default (~150 MB, downloaded once — press *Download now* before a meeting). `small` is more accurate but slower; `large-v3` needs a gaming graphics card.
- **Close languages mixed up** (Malay/Indonesian)? Set *Meeting speaks* / *I speak* to the exact language. With Auto-detect, LINGUA uses the language heard most in recent sentences when it's unsure, and Malay–English mixed in one sentence is transcribed as spoken.
- **Cantonese** needs the `large-v3` model or groq to be recognised as Cantonese; smaller models write it as Chinese. Translation into Cantonese uses Google's Cantonese.
- **Vocabulary**: names and terms (e.g. `inverter aircond = penghawa dingin inverter`) are respected by every translator.
- **Caption bar**: drag it anywhere; A+/A− size; ⏭ skips to the newest voice; 🔒 click-through (Windows) lets clicks reach Zoom underneath. It may not appear over full-screen Zoom on Mac — use Zoom in a window.

## Limits
- Meeting audio arrives as one mix, so captions say "Meeting" rather than each person's name.
- Others hear an AI voice, not your real voice (except the fallback described above).
- Without headphones, your microphone can hear the meeting; LINGUA skips sentences that match what it just heard from the meeting, but headphones are more reliable.
- Arabic, Thai, Khmer, Burmese and Indic scripts display with your system's fonts; check them on your computer.

## For developers
```
lingua/ui.py         window, caption overlay, shortcuts, speed panel
lingua/engine.py     the two directions: live captions, no-drop queue, echo filters, fallbacks, latency stats
lingua/audio.py      capture, loopback, virtual-mic output, anti-aliased resampling
lingua/vad.py        splits audio into sentences
lingua/stt.py        Whisper locally (faster-whisper) or on Groq
lingua/translate.py  Google free / MyMemory / Gemini, vocabulary protection, timeouts
lingua/tts.py        Microsoft Edge neural voices, clause by clause
lingua/languages.py  language registry: add a row to add a language
tests/               unit tests (python -m pytest -q tests), run before every build
```
Building the app yourself: `pip install -r requirements.txt -r requirements-dev.txt`, then `python tools/make_icons.py` (creates the icons the build needs), then `pyinstaller lingua.spec`. Pushing to `main` runs the tests and builds test copies; pushing a tag like `v1.2.0` publishes a release.
