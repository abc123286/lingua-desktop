"""LINGUA Desktop window + floating caption overlay (tkinter, ships with Python)."""
import datetime
import queue
import sys
import threading
import tkinter as tk
from tkinter import ttk

from . import __version__, audio, config, languages
from .engine import Direction
from .stt import STT
from .translate import Translator

AUTO = "Auto-detect"
MODELS = ["tiny", "base", "small", "medium", "large-v3"]
MODEL_HELP = {"tiny": "fastest, least accurate", "base": "fast (recommended for laptops)", "small": "more accurate, slower",
              "medium": "accurate, needs a strong PC", "large-v3": "best, needs a gaming GPU"}
IS_MAC = sys.platform == "darwin"
HOTKEYS = {"in": "<ctrl>+<alt>+h", "out": "<ctrl>+<alt>+m", "overlay": "<ctrl>+<alt>+o"}


def lang_to_name(code, allow_auto=False):
    if allow_auto and (not code or code == "auto"):
        return AUTO
    return languages.name(code)


def name_to_lang(name):
    if name == AUTO:
        return "auto"
    return languages.NAME_TO_CODE.get(name, "en")


class Overlay(tk.Toplevel):
    """Always-on-top, semi-transparent caption bar that sits over Zoom/Teams/Meet."""

    def __init__(self, app):
        super().__init__(app.root)
        self.app = app
        c = app.cfg
        self.overrideredirect(True)
        self.attributes("-topmost", True)
        try:
            self.attributes("-alpha", float(c["overlay_alpha"]))
        except tk.TclError:
            pass
        self.configure(bg="#101418")
        w = int(c["overlay_width"])
        sw, sh = self.winfo_screenwidth(), self.winfo_screenheight()
        x = c["overlay_x"] if c["overlay_x"] >= 0 else (sw - w) // 2
        y = c["overlay_y"] if c["overlay_y"] >= 0 else sh - 260
        self.geometry(f"{w}x200+{x}+{y}")

        top = tk.Frame(self, bg="#101418")
        top.pack(fill="x", padx=10, pady=(6, 0))
        self.status = tk.Label(top, text="", fg="#8b97b0", bg="#101418", font=("Segoe UI", 9))
        self.status.pack(side="left")
        for txt, cmd in (("✕", self.app.toggle_overlay), ("A+", lambda: self.bump(2)), ("A−", lambda: self.bump(-2)),
                         ("⏭", self.app.skip_voice)):
            b = tk.Label(top, text=txt, fg="#c8d0e0", bg="#101418", cursor="hand2", font=("Segoe UI", 10, "bold"))
            b.pack(side="right", padx=4)
            b.bind("<Button-1>", lambda e, f=cmd: f())

        self.main = tk.Label(self, text="LINGUA is ready. Turn on “Hear others” to see translated captions here.",
                             fg="#ffffff", bg="#101418", justify="left", anchor="w")
        self.main.pack(fill="x", padx=14, pady=(4, 0))
        self.orig = tk.Label(self, text="", fg="#8b97b0", bg="#101418", justify="left", anchor="w")
        self.orig.pack(fill="x", padx=14)
        self.me = tk.Label(self, text="", fg="#5fd4c0", bg="#101418", justify="left", anchor="w")
        self.me.pack(fill="x", padx=14, pady=(4, 8))
        self.apply_style()

        for wdg in (self, top, self.main, self.orig, self.me, self.status):
            wdg.bind("<ButtonPress-1>", self._start_move)
            wdg.bind("<B1-Motion>", self._move)
            wdg.bind("<ButtonRelease-1>", self._end_move)

    def apply_style(self):
        c = self.app.cfg
        f = int(c["overlay_font"])
        w = int(c["overlay_width"])
        family = "Segoe UI" if sys.platform == "win32" else ("Helvetica Neue" if IS_MAC else "Noto Sans")
        self.main.configure(font=(family, f, "bold"), wraplength=w - 30)
        self.orig.configure(font=(family, max(10, int(f * 0.6))), wraplength=w - 30)
        self.me.configure(font=(family, max(10, int(f * 0.65))), wraplength=w - 30)
        try:
            self.attributes("-alpha", float(c["overlay_alpha"]))
        except tk.TclError:
            pass
        self.geometry(f"{w}x{self.winfo_height() or 200}")
        self.after(50, self._fit)

    def _fit(self):
        self.update_idletasks()
        h = self.winfo_reqheight()
        self.geometry(f"{int(self.app.cfg['overlay_width'])}x{h}+{self.winfo_x()}+{self.winfo_y()}")

    def bump(self, d):
        self.app.cfg["overlay_font"] = max(12, min(48, int(self.app.cfg["overlay_font"]) + d))
        self.app.save()
        self.apply_style()

    def show_incoming(self, text, orig, src):
        self.main.configure(text=text)
        self.orig.configure(text=f"{languages.name(src)}: {orig}" if self.app.cfg["overlay_show_original"] else "")
        self._fit()

    def show_mine(self, text, tgt):
        self.me.configure(text=f"You → {languages.name(tgt)}: {text}")
        self._fit()

    def set_status(self, s):
        self.status.configure(text=s)

    def _start_move(self, e):
        self._dx, self._dy = e.x_root - self.winfo_x(), e.y_root - self.winfo_y()

    def _move(self, e):
        self.geometry(f"+{e.x_root - self._dx}+{e.y_root - self._dy}")

    def _end_move(self, e):
        self.app.cfg["overlay_x"], self.app.cfg["overlay_y"] = self.winfo_x(), self.winfo_y()
        self.app.save()


class App:
    def __init__(self):
        self.cfg = config.load()
        self.events = queue.Queue()
        self.root = tk.Tk()
        self.root.title(f"LINGUA Desktop {__version__}")
        self.root.geometry("640x760")
        self.root.minsize(560, 640)
        self.root.protocol("WM_DELETE_WINDOW", self.quit)

        self.stt = STT(self.cfg["whisper_model"], self.log)
        self.translator = Translator(self.cfg, self.log)
        self.dir = {k: Direction(k, self.cfg, self.stt, self.translator, self.events.put, self.log) for k in ("in", "out")}
        self.vars = {}
        self._build()
        self.overlay = Overlay(self)
        self.overlay_visible = True
        self.refresh_devices(first=True)
        self._start_hotkeys()
        self.root.after(100, self._poll)
        self.update_state()
        # keep the virtual mic alive (normal voice pass-through) if it's already set up
        if self.cfg["out_virtual"] and self.cfg["out_passthrough"]:
            self.root.after(800, lambda: self.dir["out"].set_translating(False))
        self.log("Welcome! Check the 'Setup help' tab the first time.")

    # ---------- helpers ----------
    def save(self):
        config.save(self.cfg)

    def log(self, msg):
        self.events.put({"type": "log", "msg": msg})

    def var(self, key, kind="str"):
        if key in self.vars:
            return self.vars[key]
        v = {"str": tk.StringVar, "bool": tk.BooleanVar, "double": tk.DoubleVar, "int": tk.IntVar}[kind]()
        self.vars[key] = v
        return v

    def bind_cfg(self, key, kind="str", on_change=None, conv=None):
        v = self.var(key, kind)
        val = self.cfg[key]
        v.set(conv[0](val) if conv else val)

        def changed(*_):
            try:
                raw = v.get()
            except tk.TclError:
                return
            self.cfg[key] = conv[1](raw) if conv else raw
            self.save()
            if on_change:
                on_change()
        v.trace_add("write", changed)
        return v

    # ---------- UI ----------
    def _build(self):
        style = ttk.Style()
        try:
            style.theme_use("vista" if sys.platform == "win32" else ("aqua" if IS_MAC else "clam"))
        except tk.TclError:
            pass
        style.configure("Big.TButton", font=("TkDefaultFont", 12, "bold"), padding=8)
        style.configure("Head.TLabel", font=("TkDefaultFont", 13, "bold"))

        r = self.root
        top = ttk.Frame(r, padding=12)
        top.pack(fill="x")
        ttk.Label(top, text="LINGUA Desktop", style="Head.TLabel").pack(side="left")
        ttk.Button(top, text="Show/hide captions", command=self.toggle_overlay).pack(side="right")

        # --- two big switches ---
        sw = ttk.Frame(r, padding=(12, 0))
        sw.pack(fill="x")
        self.cards = {}
        for k, title, sub in (("in", "🎧  Hear others in my language", "Meeting audio → captions (+ voice) for you"),
                              ("out", "🎙  Others hear me in their language", "Your voice → translated voice into the meeting")):
            f = ttk.LabelFrame(sw, text=title, padding=10)
            f.pack(fill="x", pady=5)
            ttk.Label(f, text=sub, foreground="#666").grid(row=0, column=0, columnspan=3, sticky="w")
            btn = ttk.Button(f, text="Turn ON", style="Big.TButton", command=lambda k=k: self.toggle(k))
            btn.grid(row=1, column=0, rowspan=2, padx=(0, 12), pady=(6, 0), sticky="ns")
            lamp = ttk.Label(f, text="● OFF", foreground="#999")
            lamp.grid(row=1, column=1, sticky="w", pady=(6, 0))
            ttk.Label(f, text="Translate into:" if k == "in" else "Meeting language:").grid(row=2, column=1, sticky="w")
            key = "in_lang" if k == "in" else "out_lang"
            cb = ttk.Combobox(f, values=languages.NAMES, state="readonly", width=30,
                              textvariable=self.bind_cfg(key, conv=(lang_to_name, name_to_lang)))
            cb.grid(row=2, column=2, sticky="w", padx=6)
            f.columnconfigure(2, weight=1)
            self.cards[k] = (btn, lamp)

        nb = ttk.Notebook(r, padding=(12, 6))
        nb.pack(fill="both", expand=True)
        self._tab_hear(nb)
        self._tab_me(nb)
        self._tab_engines(nb)
        self._tab_overlay(nb)
        self._tab_help(nb)

        lf = ttk.LabelFrame(r, text="Activity", padding=6)
        lf.pack(fill="both", padx=12, pady=(0, 12))
        self.logbox = tk.Text(lf, height=7, wrap="word", state="disabled", font=("TkFixedFont", 9))
        self.logbox.pack(fill="both", expand=True)

    def _row(self, parent, row, label, widget, hint=None):
        ttk.Label(parent, text=label).grid(row=row, column=0, sticky="w", pady=4, padx=(0, 8))
        widget.grid(row=row, column=1, sticky="ew", pady=4)
        if hint:
            ttk.Label(parent, text=hint, foreground="#777", wraplength=520).grid(row=row + 1, column=0, columnspan=2, sticky="w")
        parent.columnconfigure(1, weight=1)

    def _tab_hear(self, nb):
        t = ttk.Frame(nb, padding=10)
        nb.add(t, text="Hear others")
        restart = lambda: self.dir["in"].restart()
        self.cb_in_source = ttk.Combobox(t, state="readonly", textvariable=self.bind_cfg("in_source", on_change=restart))
        self._row(t, 0, "Meeting audio comes from", self.cb_in_source,
                  "Windows: your speakers/headphones (loopback). Mac: “BlackHole 2ch” (see Setup help).")
        self._row(t, 2, "Meeting speaks", ttk.Combobox(t, state="readonly", values=[AUTO] + languages.NAMES,
                  textvariable=self.bind_cfg("in_speaker_lang", conv=(lambda c: lang_to_name(c, True), name_to_lang))),
                  "Leave on Auto-detect for mixed-language meetings. Fix it (e.g. Malay) if detection mixes up close languages.")
        self._row(t, 4, "Read translations aloud", ttk.Checkbutton(t, variable=self.bind_cfg("in_voice", "bool")),
                  "Captions are always shown. Voice works best with headphones.")
        self.cb_in_out = ttk.Combobox(t, state="readonly", textvariable=self.bind_cfg("in_voice_output", on_change=restart))
        self._row(t, 6, "Play the voice on", self.cb_in_out)
        self._row(t, 7, "Voice", ttk.Combobox(t, state="readonly", values=["Female", "Male"], textvariable=self.bind_cfg("in_gender")))
        self._row(t, 8, "Save transcript", ttk.Checkbutton(t, variable=self.bind_cfg("save_transcript", "bool")),
                  f"Text only, saved to {config.TRANSCRIPTS}. Audio is never recorded.")
        ttk.Button(t, text="Refresh device list", command=self.refresh_devices).grid(row=10, column=0, sticky="w", pady=10)

    def _tab_me(self, nb):
        t = ttk.Frame(nb, padding=10)
        nb.add(t, text="My voice")
        restart = lambda: self.dir["out"].restart()
        self.cb_out_mic = ttk.Combobox(t, state="readonly", textvariable=self.bind_cfg("out_mic", on_change=restart))
        self._row(t, 0, "My real microphone", self.cb_out_mic)
        self.cb_out_virt = ttk.Combobox(t, state="readonly", textvariable=self.bind_cfg("out_virtual", on_change=restart))
        self._row(t, 1, "Send voice to (virtual mic)", self.cb_out_virt,
                  "Windows: “CABLE Input (VB-Audio Virtual Cable)”. Mac: “BlackHole 16ch”. "
                  "Then in Zoom/Teams/Meet choose “CABLE Output” / “BlackHole 16ch” as your microphone.")
        self._row(t, 3, "I speak", ttk.Combobox(t, state="readonly", values=[AUTO] + languages.NAMES,
                  textvariable=self.bind_cfg("out_my_lang", conv=(lambda c: lang_to_name(c, True), name_to_lang))))
        self._row(t, 4, "Voice", ttk.Combobox(t, state="readonly", values=["Female", "Male"], textvariable=self.bind_cfg("out_gender")))
        self._row(t, 5, "When OFF, pass my normal voice", ttk.Checkbutton(t, variable=self.bind_cfg("out_passthrough", "bool", on_change=restart)),
                  "Keeps you audible when translation is off, so you never need to change Zoom's mic setting mid-meeting.")

    def _tab_engines(self, nb):
        t = ttk.Frame(nb, padding=10)
        nb.add(t, text="AI engines")
        mv = self.bind_cfg("whisper_model", on_change=self._model_changed)
        self._row(t, 0, "Speech model (free, on your PC)", ttk.Combobox(t, state="readonly", values=MODELS, textvariable=mv),
                  " · ".join(f"{m}: {h}" for m, h in MODEL_HELP.items()))
        self._row(t, 2, "Translator", ttk.Combobox(t, state="readonly", values=["google_free", "gemini"],
                  textvariable=self.bind_cfg("translator")),
                  "google_free: no sign-up. gemini: smarter, uses context + your vocabulary; free key at aistudio.google.com.")
        e = ttk.Entry(t, show="•", textvariable=self.bind_cfg("gemini_key"))
        self._row(t, 4, "Gemini API key", e)
        self._row(t, 5, "Gemini model", ttk.Entry(t, textvariable=self.bind_cfg("gemini_model")))
        self._row(t, 6, "Voice speed", ttk.Scale(t, from_=0.7, to=1.5, variable=self.bind_cfg("rate", "double")))
        self._row(t, 7, "Mic sensitivity", ttk.Scale(t, from_=6.0, to=1.5, variable=self.bind_cfg("sensitivity", "double", on_change=self._seg_changed)),
                  "Slide right if quiet speech is missed, left if background noise triggers it.")
        self._row(t, 9, "Pause that ends a sentence (ms)", ttk.Spinbox(t, from_=300, to=2000, increment=100,
                  textvariable=self.bind_cfg("silence_ms", "int", on_change=self._seg_changed)),
                  "Shorter = faster but may cut sentences; longer = more complete sentences.")
        self._row(t, 11, "Longest piece before translating (s)", ttk.Spinbox(t, from_=3, to=15, increment=1,
                  textvariable=self.bind_cfg("max_seconds", "int", on_change=self._seg_changed)),
                  "When people talk without pausing, translate every few seconds. Lower = faster captions, "
                  "higher = more complete sentences.")
        ttk.Label(t, text="Custom vocabulary (one per line, “term = translation” optional):").grid(row=13, column=0, columnspan=2, sticky="w", pady=(10, 2))
        self.gloss = tk.Text(t, height=5, wrap="word")
        self.gloss.insert("1.0", self.cfg["glossary"])
        self.gloss.grid(row=14, column=0, columnspan=2, sticky="nsew")
        self.gloss.bind("<FocusOut>", lambda e: self._save_gloss())

    def _tab_overlay(self, nb):
        t = ttk.Frame(nb, padding=10)
        nb.add(t, text="Captions & keys")
        st = lambda: self.overlay.apply_style()
        self._row(t, 0, "Caption size", ttk.Scale(t, from_=12, to=48, variable=self.bind_cfg("overlay_font", "double", on_change=st, conv=(float, lambda v: int(round(v))))))
        self._row(t, 1, "Caption width", ttk.Scale(t, from_=400, to=1800, variable=self.bind_cfg("overlay_width", "double", on_change=st, conv=(float, lambda v: int(round(v))))))
        self._row(t, 2, "Transparency", ttk.Scale(t, from_=0.4, to=1.0, variable=self.bind_cfg("overlay_alpha", "double", on_change=st)))
        self._row(t, 3, "Show original text", ttk.Checkbutton(t, variable=self.bind_cfg("overlay_show_original", "bool")))
        mod = "Ctrl+Option" if IS_MAC else "Ctrl+Alt"
        ttk.Label(t, justify="left", text=(
            f"\nShortcuts that work while you're in Zoom/Teams/Meet:\n"
            f"   {mod}+H   Hear others ON/OFF\n"
            f"   {mod}+M   Translate my voice ON/OFF\n"
            f"   {mod}+O   Show/hide captions\n\n"
            "Drag the caption bar anywhere. A+ / A− change size, ⏭ skips the current voice, ✕ hides it."
            + ("\n\nMac: allow Terminal/Python in System Settings → Privacy & Security → Accessibility for shortcuts." if IS_MAC else "")
        )).grid(row=4, column=0, columnspan=2, sticky="w")

    def _tab_help(self, nb):
        t = ttk.Frame(nb, padding=10)
        nb.add(t, text="Setup help")
        txt = tk.Text(t, wrap="word", height=14)
        txt.pack(fill="both", expand=True)
        if IS_MAC:
            help_text = (
                "ONE-TIME SETUP (Mac)\n\n"
                "1. Install BlackHole (free): https://existential.audio/blackhole/ — install BOTH “BlackHole 2ch” and “BlackHole 16ch”.\n\n"
                "2. To HEAR OTHERS: open “Audio MIDI Setup” → + → Create Multi-Output Device → tick your headphones/speakers AND "
                "“BlackHole 2ch”. In Zoom → Settings → Audio → Speaker, choose that Multi-Output Device. "
                "In LINGUA → Hear others → “Meeting audio comes from” = BlackHole 2ch.\n\n"
                "3. To be TRANSLATED: in LINGUA → My voice → “Send voice to” = BlackHole 16ch. "
                "In Zoom → Settings → Audio → Microphone, choose “BlackHole 16ch”.\n\n"
                "4. Allow the microphone for Terminal when macOS asks.\n\n"
            )
        else:
            help_text = (
                "ONE-TIME SETUP (Windows)\n\n"
                "1. HEAR OTHERS works straight away: LINGUA listens to what your speakers/headphones play. "
                "Pick your headphones in “Meeting audio comes from”.\n\n"
                "2. To be TRANSLATED: install VB-Audio Virtual Cable (free): https://vb-audio.com/Cable/ → run the installer as "
                "administrator → restart the PC.\n"
                "   In LINGUA → My voice → “Send voice to” = CABLE Input (VB-Audio Virtual Cable).\n"
                "   In Zoom → Settings → Audio → Microphone = “CABLE Output (VB-Audio Virtual Cable)”. "
                "(Teams: Settings → Devices. Meet: ⋮ → Settings → Audio.)\n\n"
            )
        help_text += (
            "USING IT\n"
            "• “Hear others” ON → translated captions float over any app.\n"
            "• “Others hear me” ON → speak normally; the meeting hears your translated voice. "
            "OFF → they hear your normal voice (if pass-through is ticked).\n"
            "• Turn off Zoom's own noise suppression (“Original sound”) for a clearer translated voice.\n"
            "• Each person who wants their own language can run LINGUA on their own computer.\n\n"
            "PRIVACY: speech recognition runs on your PC. Text is sent to the translator (Google/Gemini) and "
            "the voice service (Microsoft Edge). No audio is recorded or saved."
        )
        txt.insert("1.0", help_text)
        txt.configure(state="disabled")

    # ---------- actions ----------
    def _save_gloss(self):
        self.cfg["glossary"] = self.gloss.get("1.0", "end").strip()
        self.save()

    def _model_changed(self):
        self.stt.model, self.stt.model_size = None, self.cfg["whisper_model"]
        self.log(f"Speech model set to '{self.cfg['whisper_model']}'. It loads when translation starts.")

    def _seg_changed(self):
        for d in self.dir.values():
            if d.seg:
                d.seg.sensitivity = float(self.cfg["sensitivity"])
                d.seg.silence_blocks = max(2, int(int(self.cfg["silence_ms"]) / 50))
                d.seg.max_samples = int(float(self.cfg.get("max_seconds", 6)) * 16000)

    def refresh_devices(self, first=False):
        try:
            sources, mics, spk = audio.list_meeting_sources(), audio.list_microphones(), audio.list_speakers()
        except Exception as e:
            self.log(f"Could not list audio devices: {e}")
            return
        self.cb_in_source["values"] = sources
        self.cb_in_out["values"] = [""] + spk
        self.cb_out_mic["values"] = [""] + mics
        self.cb_out_virt["values"] = spk
        if first:
            if not self.cfg["in_source"]:
                self.var("in_source").set(audio.guess_meeting_source())
            if not self.cfg["out_virtual"]:
                g = audio.guess_virtual_output()
                if g:
                    self.var("out_virtual").set(g)
                    self.log(f"Found virtual mic: {g}")
                else:
                    self.log("No virtual mic found yet. Needed only for “Others hear me” (see Setup help).")
        if not first:
            self.log("Device list refreshed.")

    def toggle(self, k):
        d = self.dir[k]
        self._save_gloss()
        new = not d.translating
        threading.Thread(target=d.set_translating, args=(new,), daemon=True).start()
        self.log(("Hear others" if k == "in" else "Translate my voice") + (" → ON" if new else " → OFF"))

    def skip_voice(self):
        for d in self.dir.values():
            d.skip_voice()

    def toggle_overlay(self):
        self.overlay_visible = not self.overlay_visible
        (self.overlay.deiconify if self.overlay_visible else self.overlay.withdraw)()

    def update_state(self):
        for k, (btn, lamp) in self.cards.items():
            on = self.dir[k].translating
            btn.configure(text="Turn OFF" if on else "Turn ON")
            lamp.configure(text="● ON" if on else ("● OFF (normal voice passes)" if k == "out" and self.dir[k].running else "● OFF"),
                           foreground="#1a9e60" if on else "#999")
        s_in = "ON" if self.dir["in"].translating else "off"
        s_out = "ON" if self.dir["out"].translating else "off"
        self.overlay.set_status(f"LINGUA   Hear: {s_in}   Speak: {s_out}")

    def _start_hotkeys(self):
        try:
            from pynput import keyboard
            put = self.events.put
            self.hk = keyboard.GlobalHotKeys({
                HOTKEYS["in"]: lambda: put({"type": "hotkey", "k": "in"}),
                HOTKEYS["out"]: lambda: put({"type": "hotkey", "k": "out"}),
                HOTKEYS["overlay"]: lambda: put({"type": "hotkey", "k": "overlay"}),
            })
            self.hk.daemon = True
            self.hk.start()
        except Exception as e:
            self.log(f"Keyboard shortcuts unavailable ({e}). Use the buttons instead.")

    def _write_transcript(self, ev):
        try:
            config.TRANSCRIPTS.mkdir(parents=True, exist_ok=True)
            f = config.TRANSCRIPTS / (datetime.date.today().isoformat() + ".txt")
            who = "Meeting" if ev["dir"] == "in" else "Me"
            ts = datetime.datetime.fromtimestamp(ev["t"]).strftime("%H:%M:%S")
            with open(f, "a", encoding="utf-8") as fh:
                fh.write(f"[{ts}] {who} ({languages.name(ev['src'])}): {ev['orig']}\n")
                if ev["text"] and ev["text"] != ev["orig"]:
                    fh.write(f"           → {languages.name(ev['tgt'])}: {ev['text']}\n")
        except Exception as e:
            self.log(f"Could not save transcript: {e}")

    def _poll(self):
        try:
            while True:
                ev = self.events.get_nowait()
                t = ev.get("type")
                if t == "log":
                    self.logbox.configure(state="normal")
                    self.logbox.insert("end", datetime.datetime.now().strftime("%H:%M:%S  ") + ev["msg"] + "\n")
                    self.logbox.see("end")
                    self.logbox.configure(state="disabled")
                elif t == "state":
                    self.update_state()
                elif t == "hotkey":
                    if ev["k"] == "overlay":
                        self.toggle_overlay()
                    else:
                        self.toggle(ev["k"])
                elif t == "speaking":
                    if ev["dir"] == "in" and ev["on"]:
                        self.overlay.set_status("LINGUA   ● listening to the meeting…")
                    elif ev["dir"] == "out" and ev["on"]:
                        self.overlay.set_status("LINGUA   ● you are speaking…")
                    else:
                        self.update_state()
                elif t == "caption":
                    text = ev["text"] or "(translation failed) " + ev["orig"]
                    if ev["dir"] == "in":
                        self.overlay.show_incoming(text, ev["orig"], ev["src"])
                    else:
                        self.overlay.show_mine(text, ev["tgt"])
                    self.log(f"{'Meeting' if ev['dir'] == 'in' else 'Me'} [{languages.name(ev['src'])}→"
                             f"{languages.name(ev['tgt'])}, {ev['latency']:.1f}s]: {text}")
                    if self.cfg["save_transcript"]:
                        self._write_transcript(ev)
        except queue.Empty:
            pass
        self.root.after(80, self._poll)

    def quit(self):
        self._save_gloss()
        for d in self.dir.values():
            d.shutdown()
        self.save()
        self.root.destroy()

    def run(self):
        self.root.mainloop()


def main():
    try:
        import soundcard  # noqa: F401
        import faster_whisper  # noqa: F401
    except Exception as e:
        msg = f"Missing parts. Run the install script first.\n\n{e}"
        print(msg)
        try:
            from tkinter import messagebox
            r = tk.Tk(); r.withdraw(); messagebox.showerror("LINGUA", msg); r.destroy()
        except Exception:
            pass
        return
    App().run()
