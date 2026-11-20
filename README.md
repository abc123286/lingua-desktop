# LINGUA Desktop: live translation for any meeting app

LINGUA Desktop runs **beside** Zoom, Microsoft Teams, Google Meet, Webex, WhatsApp/Telegram desktop calls, or even a YouTube video. You switch it on and off whenever you like.

| Switch | What it does |
|---|---|
| 🎧 **Hear others in my language** | Listens to the meeting's sound and shows translated captions in a floating bar on top of every window. It can also read the translations aloud. |
| 🎙 **Others hear me in their language** | You speak normally. The meeting hears a translated AI voice through a "virtual microphone". When this is OFF, your normal voice goes through. |

Everything is **free**:
- Speech recognition: Whisper, which runs on your own computer.
- Translation: Google Translate (no sign-up), or Google Gemini's free tier for smarter, context-aware translation.
- Voices: Microsoft Edge's free neural voices, covering 100+ languages including Malay, Tamil (Malaysia), Cantonese, Thai, Khmer, Burmese and Lao.

---

## 1. Install (one time)

### Windows
1. Install **Python 3.12** from https://www.python.org/downloads/. On the first screen, tick **"Add python.exe to PATH"**.
2. Double-click **`1_INSTALL_Windows.bat`** and wait until it says *Done*.
3. *(Only needed for "Others hear me")* Install **VB-Audio Virtual Cable** (free) from https://vb-audio.com/Cable/. Run its installer as administrator, then restart the PC.

### Mac
1. Install **Python 3.12** from https://www.python.org/downloads/macos/.
2. Install **BlackHole** (free) from https://existential.audio/blackhole/. Install both **BlackHole 2ch** and **BlackHole 16ch**.
3. Double-click **`1_INSTALL_Mac.command`**. If macOS blocks it, right-click it → Open.

## 2. Start
Double-click **`2_START_Windows.bat`** or **`2_START_Mac.command`**.
The first time you switch on translation, the speech model downloads. The default "small" model is about 500 MB, and it's only downloaded once.

## 3. Connect it to your meeting app

### Hear others (captions)
- **Windows:** nothing to set up. In *Hear others*, choose the speakers or headphones the meeting plays on.
- **Mac:** open **Audio MIDI Setup** → **+** → *Create Multi-Output Device*. Tick your headphones **and** *BlackHole 2ch*. In Zoom → Settings → Audio → **Speaker**, pick that Multi-Output Device. In LINGUA, set *Meeting audio comes from* to **BlackHole 2ch**.

### Others hear me (translated voice)
| | LINGUA → *Send voice to* | Zoom / Teams / Meet → **Microphone** |
|---|---|---|
| Windows | CABLE Input (VB-Audio Virtual Cable) | **CABLE Output** (VB-Audio Virtual Cable) |
| Mac | BlackHole 16ch | **BlackHole 16ch** |

Keep *"When OFF, pass my normal voice"* ticked. Then you only switch translation ON/OFF in LINGUA, and never have to touch Zoom's settings again.
In Zoom, also turn off background-noise suppression (or turn on "Original sound"), so the AI voice isn't muffled.

## 4. Shortcuts (they work while you're inside Zoom)
- **Ctrl+Alt+H**: Hear others ON/OFF
- **Ctrl+Alt+M**: Translate my voice ON/OFF
- **Ctrl+Alt+O**: show/hide the caption bar

On a Mac, these are Ctrl+Option. You also need to allow Terminal under *System Settings → Privacy & Security → Accessibility*. If a shortcut doesn't respond on a Mac, use the buttons.

You can drag the caption bar anywhere. Use **A+ / A−** to change the size, **⏭** to skip the current voice, and **✕** to hide the bar.

## 5. Tips
- **Speed vs accuracy:** under *AI engines → Speech model*, choose `base` on older laptops, `small` for most PCs, or `medium`/`large-v3` if you have a strong PC or a gaming graphics card. If the activity log says "Falling behind", pick a smaller model.
- **Malay vs Indonesian (or other close languages) getting mixed up?** Set *Meeting speaks* / *I speak* to the exact language instead of Auto-detect.
- **Better translation:** get a free key at https://aistudio.google.com/apikey. Paste it in *AI engines*, and set Translator = `gemini`. Gemini uses the last few sentences as context and respects your vocabulary list. If Gemini fails or hits its free limit, LINGUA automatically falls back to Google Translate.
- **Custom vocabulary:** add names, products and terms (e.g. `inverter aircond = penghawa dingin inverter`). These help both recognition and translation.
- **Several languages in one meeting:** "Others hear me" speaks one meeting language at a time. For everyone to get their own language, each person runs LINGUA with *Hear others* switched on.

## How it works
```
Meeting sound ─► sentence detector ─► Whisper (on your PC) ─► translator ─► caption bar (+ voice to your headphones)
Your mic      ─► sentence detector ─► Whisper (on your PC) ─► translator ─► Edge voice ─► virtual mic ─► Zoom
```
Translation starts after each natural pause, typically **1.5–4 seconds** after you stop talking. The exact delay depends on your PC and internet.

## Privacy
- Speech recognition runs on your own computer.
- Only the recognised **text** is sent to the translator (Google or Gemini) and to the voice service (Microsoft).
- No audio is ever recorded or saved.
- Transcripts (text only) are saved only if you tick *Save transcript*. They go to `~/.lingua_desktop/transcripts`.
- Tell meeting participants when you use AI translation, and follow your company's rules for confidential meetings.

## Limits of this free version
- Free services can rate-limit or change without notice. Google Translate's free endpoint is unofficial.
- The meeting's audio arrives as one mixed sound, so captions say "Meeting" rather than each person's name.
- Speaking in your own voice (voice cloning) isn't included.
- Captions appear per sentence, not word by word.

## Project layout (for developers)
```
lingua/ui.py         window, floating caption overlay, hotkeys
lingua/engine.py     the two directions (hear / speak) and pass-through
lingua/audio.py      device capture, loopback, virtual-mic output
lingua/vad.py        splits audio into sentences
lingua/stt.py        Whisper speech recognition (faster-whisper)
lingua/translate.py  translation engines (Google free, Gemini), easy to add more
lingua/tts.py        Microsoft Edge neural voices
lingua/languages.py  language registry: add a row to add a language
```
