"""LINGUA Desktop window + floating caption overlay (tkinter, ships with Python)."""
import collections
import datetime
import queue
import sys
import threading
import tkinter as tk
from tkinter import messagebox, ttk

from . import __version__, audio, config, languages
from .engine import Direction, EchoMemory, Stats
from .stt import STT
from .translate import Translator

AUTO = "Auto-detect"
MODELS = ["tiny", "base", "small", "medium", "large-v3"]
MODEL_HELP = {"tiny": "fastest, least accurate", "base": "fast (default)", "small": "more accurate, slower",
              "medium": "accurate, needs a strong PC", "large-v3": "best, needs a gaming GPU"}
IS_MAC = sys.platform == "darwin"
IS_WIN = sys.platform == "win32"

PRIVACY_TEXT = (
    "Before you start, please know what LINGUA sends where:\n\n"
    "• Speech recognition runs on this computer, unless you choose the fast cloud option (Groq), which sends the audio "
    "of each sentence to Groq.\n"
    "• The recognised TEXT of what you and others say is sent to a translator: Google Translate's free web service, "
    "MyMemory (when Google is busy) or Google Gemini (if you add a key).\n"
    "• Translations that are read aloud are sent as text to Microsoft's voice service.\n"
    "• No audio is saved. Text transcripts are saved only if you turn that on, and are deleted after the number of days you choose.\n\n"
    "Other people in your meeting are affected too: tell them you are using an AI translator, and follow your "
    "organization's rules for confidential meetings. The free Google and Microsoft services used here are unofficial "
    "and may not allow business use.")


def lang_to_name(code, allow_auto=False):
    if allow_auto and (not code or code == "auto"):
        return AUTO
    return languages.name(code)


def name_to_lang(name):
    if name == AUTO:
        return "auto"
    return languages.NAME_TO_CODE.get(name, "en")


def enable_dpi_awareness():
    if IS_WIN:
        try:
            import ctypes
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except Exception:
            try:
                ctypes.windll.user32.SetProcessDPIAware()
            except Exception:
                pass


class Overlay(tk.Toplevel):
    """Always-on-top, semi-transparent caption bar that sits over Zoom/Teams/Meet."""
    BG = "#101418"

    def __init__(self, app):
        super().__init__(app.root)
        self.app = app
        c = app.cfg
        self.overrideredirect(True)
        self.attributes("-topmost", True)
        self.configure(bg=self.BG)
        w = int(c["overlay_width"])
        sw, sh = self.winfo_screenwidth(), self.winfo_screenheight()
        x = c["overlay_x"] if 0 <= c["overlay_x"] < sw else (sw - w) // 2
        y = c["overlay_y"] if 0 <= c["overlay_y"] < sh else sh - 300
        self.geometry(f"{w}x200+{x}+{y}")
        self.history = collections.deque(maxlen=8)
        self.live = None

        top = tk.Frame(self, bg=self.BG)
        top.pack(fill="x", padx=10, pady=(6, 0))
        self.status = tk.Label(top, text="", fg="#8b97b0", bg=self.BG, font=("Segoe UI", 9))
        self.status.pack(side="left")
        self.buttons = []
        for txt, cmd, tip in (("✕", self.app.toggle_overlay, "hide"), ("A+", lambda: self.bump(2), "bigger"),
                              ("A−", lambda: self.bump(-2), "smaller"), ("⏭", self.app.skip_voice, "skip to latest voice"),
                              ("🔒", self.app.toggle_clickthrough, "click-through")):
            b = tk.Label(top, text=txt, fg="#c8d0e0", bg=self.BG, cursor="hand2", font=("Segoe UI", 10, "bold"))
            b.pack(side="right", padx=4)
            b.bind("<Button-1>", lambda e, f=cmd: f())
            self.buttons.append(b)

        self.lines = tk.Frame(self, bg=self.BG)
        self.lines.pack(fill="x", padx=14, pady=(4, 0))
        self.me = tk.Label(self, text="", fg="#5fd4c0", bg=self.BG, justify="left", anchor="w")
        self.me.pack(fill="x", padx=14, pady=(4, 8))
        self.history.append(("LINGUA is ready. Turn on “Hear others” to see translated captions here.", "", ""))
        self.apply_style()

        for wdg in (self, top, self.lines, self.me, self.status):
            wdg.bind("<ButtonPress-1>", self._start_move)
            wdg.bind("<B1-Motion>", self._move)
            wdg.bind("<ButtonRelease-1>", self._end_move)

    def family(self):
        return "Segoe UI" if IS_WIN else ("Helvetica Neue" if IS_MAC else "Noto Sans")

    def apply_style(self):
        c = self.app.cfg
        try:
            self.attributes("-alpha", float(c["overlay_alpha"]))
        except tk.TclError:
            pass
        self.me.configure(font=(self.family(), max(10, int(int(c["overlay_font"]) * 0.65))), wraplength=int(c["overlay_width"]) - 30)
        self.render()

    def render(self):
        c = self.app.cfg
        f, w = int(c["overlay_font"]), int(c["overlay_width"])
        for ch in self.lines.winfo_children():
            ch.destroy()
        items = list(self.history)[-int(c.get("overlay_lines", 3)):]
        for i, (text, orig, src) in enumerate(items):
            newest = i == len(items) - 1 and not self.live
            tk.Label(self.lines, text=text, fg="#ffffff" if newest else "#aeb7c8", bg=self.BG, justify="left", anchor="w",
                     wraplength=w - 30, font=(self.family(), f if newest else max(11, int(f * 0.75)), "bold" if newest else "normal")).pack(fill="x")
            if newest and orig and c["overlay_show_original"]:
                tk.Label(self.lines, text=f"{languages.name(src)}: {orig}", fg="#8b97b0", bg=self.BG, justify="left", anchor="w",
                         wraplength=w - 30, font=(self.family(), max(10, int(f * 0.6)))).pack(fill="x")
        if self.live:
            tk.Label(self.lines, text=self.live, fg="#ffffff", bg=self.BG, justify="left", anchor="w", wraplength=w - 30,
                     font=(self.family(), f, "italic")).pack(fill="x")
        self.after(30, self._fit)

    def _fit(self):
        self.update_idletasks()
        h = self.winfo_reqheight()
        self.geometry(f"{int(self.app.cfg['overlay_width'])}x{h}+{self.winfo_x()}+{self.winfo_y()}")

    def bump(self, d):
        self.app.cfg["overlay_font"] = max(12, min(48, int(self.app.cfg["overlay_font"]) + d))
        self.app.save()
        self.apply_style()

    def show_live(self, text):
        self.live = text + " …"
        self.render()

    def show_incoming(self, text, orig, src):
        self.live = None
        self.history.append((text, orig, src))
        self.render()

    def clear_live(self):
        if self.live:
            self.live = None
            self.render()

    def show_mine(self, text, tgt, live=False):
        self.me.configure(text=f"You → {languages.name(tgt)}: {text}{' …' if live else ''}")
        self._fit()

    def set_status(self, s):
        self.status.configure(text=s)

    def set_clickthrough(self, on):
        """Windows: let mouse clicks pass through to Zoom underneath. Use the main window or Ctrl+Alt+O to undo."""
        if not IS_WIN:
            return False
        try:
            import ctypes
            hwnd = ctypes.windll.user32.GetParent(self.winfo_id()) or self.winfo_id()
            GWL_EXSTYLE, WS_EX_LAYERED, WS_EX_TRANSPARENT = -20, 0x80000, 0x20
            style = ctypes.windll.user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
            style = (style | WS_EX_LAYERED | WS_EX_TRANSPARENT) if on else (style & ~WS_EX_TRANSPARENT)
            ctypes.windll.user32.SetWindowLongW(hwnd, GWL_EXSTYLE, style)
            return True
        except Exception:
            return False

    def _start_move(self, e):
        self._dx, self._dy = e.x_root - self.winfo_x(), e.y_root - self.winfo_y()

    def _move(self, e):
        self.geometry(f"+{e.x_root - self._dx}+{e.y_root - self._dy}")

    def _end_move(self, e):
        self.app.cfg["overlay_x"], self.app.cfg["overlay_y"] = self.winfo_x(), self.winfo_y()
        self.app.save()


class App:
    def __init__(self):
        enable_dpi_awareness()
        self.cfg = config.load()
        removed = config.cleanup_transcripts(int(self.cfg.get("transcript_days", 30)))
        self.events = queue.Queue()
        self.root = tk.Tk()
        self.root.title(f"LINGUA Desktop {__version__}")
        self.root.geometry("680x820")
        self.root.minsize(580, 660)
        self.root.protocol("WM_DELETE_WINDOW", self.quit)

        self.stt = STT(self.cfg, self.log, self._stt_status, key_getter=lambda: config.get_secret("groq_key"))
        self.translator = Translator(self.cfg, self.log, key_getter=lambda: config.get_secret("gemini_key"),
                                     on_engine=lambda n: self.events.put({"type": "engine", "name": n}))
        self.echo, self.stats = EchoMemory(), Stats()
        self.dir = {k: Direction(k, self.cfg, self.stt, self.translator, self.events.put, self.log, self.echo, self.stats)
                    for k in ("in", "out")}
        self.vars = {}
        self.engine_name = ""
        self.stt_msg = ""
        self.clickthrough = False
        self.hk = None
        self._build()
        self.overlay = Overlay(self)
        self.overlay_visible = True
        self.refresh_devices(first=True)
        self._start_hotkeys()
        self.root.after(100, self._poll)
        self.root.after(2000, self._refresh_stats)
        self.update_state()
        if self.cfg["out_virtual"] and self.cfg["out_passthrough"]:
            self.root.after(800, lambda: self._bg(self.dir["out"].set_translating, False))
        if removed:
            self.log(f"Deleted {removed} transcript file(s) older than {self.cfg['transcript_days']} days.")
        self.log("Welcome! Check the 'Setup help' tab the first time.")
        if not self.cfg.get("privacy_ack"):
            self.root.after(400, self._privacy_notice)

    # ---------- helpers ----------
    def save(self):
        config.save(self.cfg)

    def log(self, msg):
        self.events.put({"type": "log", "msg": msg})

    def _bg(self, fn, *a):
        threading.Thread(target=fn, args=a, daemon=True).start()

    def _stt_status(self, state, msg):
        self.events.put({"type": "stt", "state": state, "msg": msg})

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

    def _privacy_notice(self):
        messagebox.showinfo("LINGUA Desktop: privacy", PRIVACY_TEXT, parent=self.root)
        self.cfg["privacy_ack"] = True
        self.save()

    # ---------- UI ----------
    def _build(self):
        style = ttk.Style()
        try:
            style.theme_use("vista" if IS_WIN else ("aqua" if IS_MAC else "clam"))
        except tk.TclError:
            pass
        style.configure("Big.TButton", font=("TkDefaultFont", 12, "bold"), padding=8)
        style.configure("Head.TLabel", font=("TkDefaultFont", 13, "bold"))

        r = self.root
        top = ttk.Frame(r, padding=12)
        top.pack(fill="x")
        ttk.Label(top, text="LINGUA Desktop", style="Head.TLabel").pack(side="left")
        ttk.Button(top, text="Show/hide captions", command=self.toggle_overlay).pack(side="right")

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
            lamp.grid(row=1, column=1, columnspan=2, sticky="w", pady=(6, 0))
            ttk.Label(f, text="Translate into:" if k == "in" else "Meeting language:").grid(row=2, column=1, sticky="w")
            key = "in_lang" if k == "in" else "out_lang"
            cb = ttk.Combobox(f, values=languages.NAMES, state="readonly", width=30,
                              textvariable=self.bind_cfg(key, conv=(lang_to_name, name_to_lang)))
            cb.grid(row=2, column=2, sticky="w", padx=6)
            f.columnconfigure(2, weight=1)
            self.cards[k] = (btn, lamp)

        sf = ttk.LabelFrame(r, text="Speed (measured)", padding=(10, 4))
        sf.pack(fill="x", padx=12, pady=(4, 0))
        self.stats_lbl = ttk.Label(sf, text="No measurements yet. Turn something on and speak.", foreground="#555", justify="left")
        self.stats_lbl.pack(anchor="w")
        self.status_lbl = ttk.Label(sf, text="", foreground="#555")
        self.status_lbl.pack(anchor="w")

        nb = ttk.Notebook(r, padding=(12, 6))
        nb.pack(fill="both", expand=True)
        self._tab_hear(nb)
        self._tab_me(nb)
        self._tab_engines(nb)
        self._tab_overlay(nb)
        self._tab_privacy(nb)
        self._tab_help(nb)

        lf = ttk.LabelFrame(r, text="Activity", padding=6)
        lf.pack(fill="both", padx=12, pady=(0, 12))
        self.logbox = tk.Text(lf, height=6, wrap="word", state="disabled", font=("TkFixedFont", 9))
        self.logbox.pack(fill="both", expand=True)

    def _row(self, parent, row, label, widget, hint=None):
        ttk.Label(parent, text=label).grid(row=row, column=0, sticky="w", pady=4, padx=(0, 8))
        widget.grid(row=row, column=1, sticky="ew", pady=4)
        if hint:
            ttk.Label(parent, text=hint, foreground="#777", wraplength=540).grid(row=row + 1, column=0, columnspan=2, sticky="w")
        parent.columnconfigure(1, weight=1)

    def _restart(self, k):
        self._bg(self.dir[k].restart)   # opening devices off the interface thread keeps the window responsive

    def _tab_hear(self, nb):
        t = ttk.Frame(nb, padding=10)
        nb.add(t, text="Hear others")
        self.cb_in_source = ttk.Combobox(t, state="readonly", textvariable=self.bind_cfg("in_source", on_change=lambda: self._restart("in")))
        self._row(t, 0, "Meeting audio comes from", self.cb_in_source,
                  "Windows: your speakers/headphones (captures everything they play, so mute music and notifications). "
                  "Mac: “BlackHole 2ch” (see Setup help).")
        self._row(t, 2, "Meeting speaks", ttk.Combobox(t, state="readonly", values=[AUTO] + languages.NAMES,
                  textvariable=self.bind_cfg("in_speaker_lang", conv=(lambda c: lang_to_name(c, True), name_to_lang))),
                  "Auto-detect handles mixed-language meetings. Choose the language if detection mixes up close languages (e.g. Malay/Indonesian).")
        self._row(t, 4, "Read translations aloud", ttk.Checkbutton(t, variable=self.bind_cfg("in_voice", "bool")),
                  "Captions are always shown. If the voice plays on the same speakers LINGUA listens to, it recognises and skips its own voice.")
        self.cb_in_out = ttk.Combobox(t, state="readonly", textvariable=self.bind_cfg("in_voice_output", on_change=lambda: self._restart("in")))
        self._row(t, 6, "Play the voice on", self.cb_in_out, "Best: a different device from the one above (e.g. headphones).")
        self._row(t, 8, "Voice", ttk.Combobox(t, state="readonly", values=["Female", "Male"], textvariable=self.bind_cfg("in_gender")))
        ttk.Button(t, text="Refresh device list", command=self.refresh_devices).grid(row=10, column=0, sticky="w", pady=10)

    def _tab_me(self, nb):
        t = ttk.Frame(nb, padding=10)
        nb.add(t, text="My voice")
        self.cb_out_mic = ttk.Combobox(t, state="readonly", textvariable=self.bind_cfg("out_mic", on_change=lambda: self._restart("out")))
        self._row(t, 0, "My real microphone", self.cb_out_mic)
        self.cb_out_virt = ttk.Combobox(t, state="readonly", textvariable=self.bind_cfg("out_virtual", on_change=lambda: self._restart("out")))
        self._row(t, 1, "Send voice to (virtual mic)", self.cb_out_virt,
                  "Windows: “CABLE Input (VB-Audio Virtual Cable)”. Mac: “BlackHole 16ch”. "
                  "Then in Zoom/Teams/Meet choose “CABLE Output” / “BlackHole 16ch” as your microphone.")
        self._row(t, 3, "I speak", ttk.Combobox(t, state="readonly", values=[AUTO] + languages.NAMES,
                  textvariable=self.bind_cfg("out_my_lang", conv=(lambda c: lang_to_name(c, True), name_to_lang))))
        self._row(t, 4, "Voice", ttk.Combobox(t, state="readonly", values=["Female", "Male"], textvariable=self.bind_cfg("out_gender")))
        self._row(t, 5, "When OFF, pass my normal voice", ttk.Checkbutton(t, variable=self.bind_cfg("out_passthrough", "bool", on_change=lambda: self._restart("out"))),
                  "Your microphone then stays on while LINGUA is open, sending your normal voice to the virtual mic. "
                  "The caption bar shows “Mic → meeting” whenever this is happening.")
        self._row(t, 7, "I use headphones", ttk.Checkbutton(t, variable=self.bind_cfg("out_headphones", "bool")),
                  "Without headphones your microphone can hear the meeting. LINGUA then skips sentences that match what it "
                  "just heard from the meeting, so it doesn't translate others' words as yours. Headphones are more reliable.")

    def _key_row(self, t, row, label, secret):
        frm = ttk.Frame(t)
        v = tk.StringVar(value="•" * 8 if config.get_secret(secret) else "")
        e = ttk.Entry(frm, show="•", textvariable=v)
        e.pack(side="left", fill="x", expand=True)

        def store():
            val = v.get().strip()
            if val and set(val) == {"•"}:
                return
            where = config.set_secret(secret, val)
            self.log(f"{label} {'saved to the system keychain' if where == 'keychain' else 'saved (private file)' if where == 'file' else 'could not be saved'}." if val else f"{label} removed.")
            v.set("•" * 8 if val else "")
        ttk.Button(frm, text="Save", command=store).pack(side="left", padx=4)
        self._row(t, row, label, frm)

    def _tab_engines(self, nb):
        t = ttk.Frame(nb, padding=10)
        nb.add(t, text="AI engines")
        self._row(t, 0, "Speech recognition", ttk.Combobox(t, state="readonly", values=["local", "groq"],
                  textvariable=self.bind_cfg("stt_engine", on_change=lambda: self._bg(self.stt.load))),
                  "local: free and offline, speed depends on this computer. groq: much faster cloud Whisper, free key "
                  "from console.groq.com (about 20 sentences a minute on the free plan; sends sentence audio to Groq).")
        self._key_row(t, 2, "Groq API key", "groq_key")
        mv = self.bind_cfg("whisper_model", on_change=self._model_changed)
        mfrm = ttk.Frame(t)
        ttk.Combobox(mfrm, state="readonly", values=MODELS, textvariable=mv, width=12).pack(side="left")
        ttk.Button(mfrm, text="Download now", command=lambda: self._bg(self.stt.local.load)).pack(side="left", padx=6)
        self._row(t, 3, "Local speech model", mfrm, " · ".join(f"{m}: {h}" for m, h in MODEL_HELP.items()))
        self._row(t, 5, "Live captions while speaking", ttk.Checkbutton(t, variable=self.bind_cfg("live_captions", "bool")),
                  "Refreshes the caption about every second from the sentence so far (uses more processor time).")
        self._row(t, 7, "Translator", ttk.Combobox(t, state="readonly", values=["google_free", "gemini"], textvariable=self.bind_cfg("translator")),
                  "google_free: no sign-up (MyMemory takes over if Google is busy). gemini: smarter, free key at aistudio.google.com.")
        self._key_row(t, 9, "Gemini API key", "gemini_key")
        self._row(t, 10, "Gemini model", ttk.Entry(t, textvariable=self.bind_cfg("gemini_model")))
        self._row(t, 11, "Voice speed", ttk.Scale(t, from_=0.7, to=1.5, variable=self.bind_cfg("rate", "double")))
        self._row(t, 12, "Mic sensitivity", ttk.Scale(t, from_=6.0, to=1.5, variable=self.bind_cfg("sensitivity", "double", on_change=self._seg_changed)),
                  "Slide right if quiet speech is missed, left if background noise triggers it.")
        self._row(t, 14, "Pause that ends a sentence (ms)", ttk.Spinbox(t, from_=250, to=2000, increment=50,
                  textvariable=self.bind_cfg("silence_ms", "int", on_change=self._seg_changed)))
        self._row(t, 15, "Longest piece before translating (s)", ttk.Spinbox(t, from_=2, to=15, increment=1,
                  textvariable=self.bind_cfg("max_seconds", "int", on_change=self._seg_changed)))
        ttk.Label(t, text="Vocabulary (one per line, “term = translation” optional). Used by every translator:").grid(row=16, column=0, columnspan=2, sticky="w", pady=(10, 2))
        self.gloss = tk.Text(t, height=4, wrap="word")
        self.gloss.insert("1.0", self.cfg["glossary"])
        self.gloss.grid(row=17, column=0, columnspan=2, sticky="nsew")
        self.gloss.bind("<FocusOut>", lambda e: self._save_gloss())

    def _tab_overlay(self, nb):
        t = ttk.Frame(nb, padding=10)
        nb.add(t, text="Captions & keys")
        st = lambda: self.overlay.apply_style()
        conv = (float, lambda v: int(round(v)))
        self._row(t, 0, "Caption size", ttk.Scale(t, from_=12, to=48, variable=self.bind_cfg("overlay_font", "double", on_change=st, conv=conv)))
        self._row(t, 1, "Caption width", ttk.Scale(t, from_=400, to=1800, variable=self.bind_cfg("overlay_width", "double", on_change=st, conv=conv)))
        self._row(t, 2, "Lines of history", ttk.Spinbox(t, from_=1, to=8, textvariable=self.bind_cfg("overlay_lines", "int", on_change=st)))
        self._row(t, 3, "Transparency", ttk.Scale(t, from_=0.4, to=1.0, variable=self.bind_cfg("overlay_alpha", "double", on_change=st)))
        self._row(t, 4, "Show original text", ttk.Checkbutton(t, variable=self.bind_cfg("overlay_show_original", "bool", on_change=st)))
        self._row(t, 5, "Click-through (Windows)", ttk.Checkbutton(t, variable=self.bind_cfg("overlay_clickthrough", "bool", on_change=self._apply_clickthrough)),
                  "Clicks pass through the caption bar to Zoom underneath. Untick here to move the bar again.")
        self._row(t, 7, "Keyboard shortcuts", ttk.Checkbutton(t, variable=self.bind_cfg("hotkeys_enabled", "bool", on_change=self._start_hotkeys)),
                  "Off by default. To catch shortcuts while you're in Zoom, LINGUA has to watch every key you press "
                  "(it reacts only to its own shortcuts and stores nothing). Some antivirus tools warn about this.")
        for i, (k, lbl) in enumerate((("hotkey_in", "Hear others on/off"), ("hotkey_out", "Translate my voice on/off"), ("hotkey_overlay", "Show/hide captions"))):
            self._row(t, 9 + i, lbl, ttk.Entry(t, textvariable=self.bind_cfg(k, on_change=self._start_hotkeys)))
        ttk.Label(t, foreground="#777", wraplength=540, text="Format like <ctrl>+<shift>+h. Avoid Ctrl+Alt on keyboards where it acts as AltGr."
                  + ("\nMac: allow Terminal/LINGUA in System Settings → Privacy & Security → Accessibility." if IS_MAC else "")).grid(row=12, column=0, columnspan=2, sticky="w")

    def _tab_privacy(self, nb):
        t = ttk.Frame(nb, padding=10)
        nb.add(t, text="Privacy")
        ttk.Label(t, text=PRIVACY_TEXT, wraplength=600, justify="left").grid(row=0, column=0, columnspan=2, sticky="w")
        self._row(t, 1, "Save text transcripts", ttk.Checkbutton(t, variable=self.bind_cfg("save_transcript", "bool")),
                  f"Saved to {config.TRANSCRIPTS}. Audio is never saved.")
        self._row(t, 3, "Delete transcripts after (days, 0 = never)", ttk.Spinbox(t, from_=0, to=365, textvariable=self.bind_cfg("transcript_days", "int")))

    def _tab_help(self, nb):
        t = ttk.Frame(nb, padding=10)
        nb.add(t, text="Setup help")
        txt = tk.Text(t, wrap="word", height=14)
        txt.pack(fill="both", expand=True)
        if IS_MAC:
            help_text = (
                "ONE-TIME SETUP (Mac)\n\n"
                "1. Install BlackHole (free): https://existential.audio/blackhole/ — install BOTH “BlackHole 2ch” and “BlackHole 16ch”.\n\n"
                "2. To HEAR OTHERS: open “Audio MIDI Setup” → + → Create Multi-Output Device → tick your headphones and "
                "“BlackHole 2ch”. In Zoom → Settings → Audio → Speaker, choose that Multi-Output Device. "
                "In LINGUA → Hear others → “Meeting audio comes from” = BlackHole 2ch. Don't add BlackHole 16ch to it.\n\n"
                "3. To be TRANSLATED: in LINGUA → My voice → “Send voice to” = BlackHole 16ch. "
                "In Zoom → Settings → Audio → Microphone, choose “BlackHole 16ch”.\n\n"
                "4. Allow the microphone when macOS asks.\n\n")
        else:
            help_text = (
                "ONE-TIME SETUP (Windows)\n\n"
                "1. HEAR OTHERS works straight away: pick your speakers/headphones in “Meeting audio comes from”.\n\n"
                "2. To be TRANSLATED: install VB-Audio Virtual Cable (free): https://vb-audio.com/Cable/ → run the installer as "
                "administrator → restart the PC. In LINGUA → My voice → “Send voice to” = CABLE Input. "
                "In Zoom → Settings → Audio → Microphone = “CABLE Output”.\n\n")
        help_text += (
            "FOR THE FASTEST CAPTIONS\n"
            "• AI engines → Speech recognition = groq (free key): finished sentences are recognised in well under a second.\n"
            "• Local speech model = tiny, and keep “Live captions while speaking” on: live captions run on this computer and update about every second.\n"
            "• Check the Speed box for your real numbers.\n"
            "• Use headphones, and turn off Zoom's noise suppression (“Original sound”).\n\n"
            "LIMITS\n"
            "• Others hear an AI voice. If a translation or the voice fails, your own recorded words are sent instead.\n"
            "• The caption bar may not appear over full-screen Zoom on Mac; use Zoom in a window.\n"
            "• Text in complex scripts (Arabic, Thai, Khmer, Indic) depends on your system's fonts.")
        txt.insert("1.0", help_text)
        txt.configure(state="disabled")

    # ---------- actions ----------
    def _save_gloss(self):
        self.cfg["glossary"] = self.gloss.get("1.0", "end").strip()
        self.save()

    def _model_changed(self):
        self._bg(self.stt.set_model, self.cfg["whisper_model"])
        self.log(f"Speech model set to '{self.cfg['whisper_model']}'. Press 'Download now' or it loads when translation starts.")

    def _seg_changed(self):
        for d in self.dir.values():
            if d.seg:
                d.seg.sensitivity = float(self.cfg["sensitivity"])
                d.seg.silence_blocks = max(2, int(int(self.cfg["silence_ms"]) / 50))
                d.seg.max_samples = int(float(self.cfg.get("max_seconds", 6)) * 16000)

    def _apply_clickthrough(self):
        on = bool(self.cfg.get("overlay_clickthrough"))
        if not self.overlay.set_clickthrough(on) and on:
            self.log("Click-through only works on Windows.")

    def toggle_clickthrough(self):
        self.var("overlay_clickthrough", "bool").set(not self.cfg.get("overlay_clickthrough"))

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
        else:
            self.log("Device list refreshed.")

    def toggle(self, k):
        self._save_gloss()
        new = not self.dir[k].translating
        self._bg(self.dir[k].set_translating, new)
        self.log(("Hear others" if k == "in" else "Translate my voice") + (" → ON" if new else " → OFF"))

    def skip_voice(self):
        for d in self.dir.values():
            d.skip_voice()

    def toggle_overlay(self):
        self.overlay_visible = not self.overlay_visible
        (self.overlay.deiconify if self.overlay_visible else self.overlay.withdraw)()

    def update_state(self):
        for k, (btn, lamp) in self.cards.items():
            d = self.dir[k]
            st = d.status
            btn.configure(text="Turn OFF" if d.translating else "Turn ON")
            if st == "loading":
                lamp.configure(text="● Loading speech model… (sentences are kept and translated once it's ready)", foreground="#b8860b")
            elif st == "on":
                lamp.configure(text="● ON", foreground="#1a9e60")
            elif d.passthrough:
                lamp.configure(text="● OFF — your microphone is passing your normal voice to the meeting", foreground="#2457c5")
            else:
                lamp.configure(text="● OFF", foreground="#999")
        s_in, s_out = self.dir["in"].status, self.dir["out"].status
        extra = "   🎙 Mic → meeting (normal voice)" if self.dir["out"].passthrough else ""
        self.overlay.set_status(f"LINGUA   Hear: {s_in}   Speak: {s_out}{extra}")

    def _refresh_stats(self):
        s = self.stats.summary()
        names = (("in_live", "Meeting → live caption"), ("in_caption", "Meeting → final caption"), ("in_voice", "Meeting → voice"),
                 ("out_live", "Me → live preview"), ("out_caption", "Me → translated text"), ("out_voice", "Me → voice in meeting"))
        rows = [f"{lbl}: typical {s[k][0]:.1f} s · slowest 5% {s[k][1]:.1f} s ({s[k][2]})" for k, lbl in names if k in s]
        if rows:
            self.stats_lbl.configure(text="\n".join(rows) + "\nMeasured from the end of each spoken piece (live: from the moment of the update).")
        self.status_lbl.configure(text=" · ".join(x for x in (self.stt_msg, f"Translator in use: {self.engine_name}" if self.engine_name else "") if x))
        self.root.after(2000, self._refresh_stats)

    def _start_hotkeys(self):
        try:
            if self.hk:
                self.hk.stop()
                self.hk = None
        except Exception:
            pass
        if not self.cfg.get("hotkeys_enabled"):
            return
        try:
            from pynput import keyboard
            put = self.events.put
            self.hk = keyboard.GlobalHotKeys({
                self.cfg["hotkey_in"]: lambda: put({"type": "hotkey", "k": "in"}),
                self.cfg["hotkey_out"]: lambda: put({"type": "hotkey", "k": "out"}),
                self.cfg["hotkey_overlay"]: lambda: put({"type": "hotkey", "k": "overlay"}),
            })
            self.hk.daemon = True
            self.hk.start()
            self.log("Keyboard shortcuts on.")
        except Exception as e:
            self.log(f"Keyboard shortcuts unavailable ({e}). Check the format, e.g. <ctrl>+<shift>+h.")

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
            config._private(f)
        except Exception as e:
            self.log(f"Could not save transcript: {e}")

    def _poll(self):
        try:
            for _ in range(200):
                ev = self.events.get_nowait()
                t = ev.get("type")
                if t == "log":
                    self.logbox.configure(state="normal")
                    self.logbox.insert("end", datetime.datetime.now().strftime("%H:%M:%S  ") + ev["msg"] + "\n")
                    self.logbox.see("end")
                    self.logbox.configure(state="disabled")
                elif t == "state":
                    self.update_state()
                elif t == "stt":
                    self.stt_msg = ev["msg"]
                    self.log(ev["msg"])
                    self.update_state()
                elif t == "engine":
                    if self.engine_name and self.engine_name != ev["name"]:
                        self.log(f"Translator switched to {ev['name']} (vocabulary still applied).")
                    self.engine_name = ev["name"]
                elif t == "hotkey":
                    if ev["k"] == "overlay":
                        self.toggle_overlay()
                    else:
                        self.toggle(ev["k"])
                elif t == "speaking":
                    if not ev["on"] and ev["dir"] == "in":
                        self.overlay.clear_live()
                    self.update_state()
                elif t == "live":
                    text = ev["text"] or ev["orig"]
                    if ev["dir"] == "in":
                        self.overlay.show_live(text)
                    else:
                        self.overlay.show_mine(text, ev["tgt"], live=True)
                elif t == "caption":
                    text = ev["text"] or "(not translated) " + ev["orig"]
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
        self.root.after(60, self._poll)

    def quit(self):
        self._save_gloss()
        for d in self.dir.values():
            d.shutdown()
        config.save(self.cfg, delay=0)
        self.root.destroy()

    def run(self):
        if self.cfg.get("overlay_clickthrough"):
            self.root.after(500, self._apply_clickthrough)
        self.root.mainloop()


def main():
    try:
        import soundcard  # noqa: F401
        import faster_whisper  # noqa: F401
    except Exception as e:
        msg = f"Missing parts. Run the install script first.\n\n{e}"
        print(msg)
        try:
            r = tk.Tk()
            r.withdraw()
            messagebox.showerror("LINGUA", msg)
            r.destroy()
        except Exception:
            pass
        return
    App().run()
