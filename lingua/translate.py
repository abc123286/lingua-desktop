"""Translation engines (pluggable). Both are free:

- google_free : Google Translate's free web endpoint (via deep-translator). No key, no sign-up.
- gemini      : Google Gemini free tier (key from aistudio.google.com). Smarter: uses the
                previous sentences and your vocabulary list. Falls back to google_free on errors.

To add a provider, write a class with translate(text, src, tgt, context, glossary) -> str
and register it in ENGINES.
"""
import json
import ssl
import time
import urllib.error
import urllib.request

from . import languages


def _ssl_ctx():
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except Exception:
        return ssl.create_default_context()


class GoogleFree:
    label = "Google Translate (free, no key)"

    def translate(self, text, src, tgt, context="", glossary=""):
        from deep_translator import GoogleTranslator
        target = languages.google_code(tgt)
        tries = [target]
        if tgt == "yue":
            tries.append("zh-TW")
        last = None
        for t in tries:
            try:
                out = GoogleTranslator(source="auto", target=t).translate(text)
                if out:
                    return out
            except Exception as e:
                last = e
        raise last or RuntimeError("Empty translation")


class Gemini:
    label = "Google Gemini (free key, smarter)"

    def __init__(self, key, model):
        self.key, self.model = key.strip(), (model or "gemini-flash-latest").strip()
        self.cooldown_until = 0

    def translate(self, text, src, tgt, context="", glossary=""):
        if not self.key:
            raise RuntimeError("No Gemini key set")
        if time.time() < self.cooldown_until:
            raise RuntimeError("Gemini rate-limited, cooling down")
        prompt = (
            "You are a live meeting interpreter. Translate the speech segment below into "
            f"{languages.name(tgt)}. Translate the meaning, not word for word. Keep the tone, names and "
            "numbers. Use natural spoken style. If it is an incomplete sentence, keep it incomplete. "
            "Fix obvious speech-recognition mistakes only when context makes them clear. "
            "Reply with the translation only, nothing else.\n"
        )
        if glossary.strip():
            prompt += f"\nVocabulary to respect (term = preferred translation):\n{glossary.strip()[:1500]}\n"
        if context.strip():
            prompt += f"\nEarlier in the conversation (context only, do not translate):\n{context.strip()[-1500:]}\n"
        prompt += f"\nSegment ({languages.name(src)}): {text}"
        body = json.dumps({
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {"temperature": 0.2},
        }).encode()
        url = (f"https://generativelanguage.googleapis.com/v1beta/models/{self.model}:generateContent")
        req = urllib.request.Request(url, data=body, headers={
            "Content-Type": "application/json", "x-goog-api-key": self.key})
        try:
            with urllib.request.urlopen(req, timeout=15, context=_ssl_ctx()) as r:
                data = json.loads(r.read().decode())
        except urllib.error.HTTPError as e:
            if e.code == 429:
                self.cooldown_until = time.time() + 30
            raise RuntimeError(f"Gemini HTTP {e.code}: {e.read()[:200]!r}")
        parts = data["candidates"][0]["content"]["parts"]
        return "".join(p.get("text", "") for p in parts).strip()


class Translator:
    def __init__(self, cfg, log):
        self.cfg, self.log = cfg, log
        self.google = GoogleFree()
        self._gem = None

    def _gemini(self):
        key, model = self.cfg.get("gemini_key", ""), self.cfg.get("gemini_model", "")
        if self._gem is None or self._gem.key != key.strip() or self._gem.model != model.strip():
            self._gem = Gemini(key, model)
        return self._gem

    def translate(self, text, src, tgt, context=""):
        if languages.same_language(src, tgt):
            return text
        glossary = self.cfg.get("glossary", "")
        if self.cfg.get("translator") == "gemini" and self.cfg.get("gemini_key"):
            try:
                return self._gemini().translate(text, src, tgt, context, glossary)
            except Exception as e:
                self.log(f"Gemini failed ({e}); using Google Translate for this sentence.")
        return self.google.translate(text, src, tgt, context, glossary)
