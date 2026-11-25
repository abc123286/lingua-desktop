"""Language registry.

This is data, not logic: add a row to support another language.
Columns: code, English name, Google Translate code, Edge voice locale (preferred).
Speech recognition (Whisper) detects ~99 languages by itself; the codes it
returns are mapped back with WHISPER_TO_CODE.
"""

LANGS = [
    ("en", "English", "en", "en-US"),
    ("zh-CN", "Mandarin Chinese (Simplified)", "zh-CN", "zh-CN"),
    ("zh-TW", "Mandarin Chinese (Traditional)", "zh-TW", "zh-TW"),
    ("yue", "Cantonese", "yue", "zh-HK"),
    ("ms", "Malay", "ms", "ms-MY"),
    ("id", "Indonesian", "id", "id-ID"),
    ("ja", "Japanese", "ja", "ja-JP"),
    ("ko", "Korean", "ko", "ko-KR"),
    ("th", "Thai", "th", "th-TH"),
    ("vi", "Vietnamese", "vi", "vi-VN"),
    ("ar", "Arabic", "ar", "ar-SA"),
    ("hi", "Hindi", "hi", "hi-IN"),
    ("ta", "Tamil", "ta", "ta-MY"),
    ("bn", "Bengali", "bn", "bn-BD"),
    ("es", "Spanish", "es", "es-ES"),
    ("fr", "French", "fr", "fr-FR"),
    ("de", "German", "de", "de-DE"),
    ("pt-BR", "Portuguese (Brazil)", "pt", "pt-BR"),
    ("pt-PT", "Portuguese (Portugal)", "pt", "pt-PT"),
    ("it", "Italian", "it", "it-IT"),
    ("ru", "Russian", "ru", "ru-RU"),
    ("tr", "Turkish", "tr", "tr-TR"),
    ("nl", "Dutch", "nl", "nl-NL"),
    ("fil", "Filipino", "tl", "fil-PH"),
    ("my", "Burmese", "my", "my-MM"),
    ("km", "Khmer", "km", "km-KH"),
    ("lo", "Lao", "lo", "lo-LA"),
    ("ne", "Nepali", "ne", "ne-NP"),
    ("ur", "Urdu", "ur", "ur-PK"),
    ("sw", "Swahili", "sw", "sw-KE"),
    ("te", "Telugu", "te", "te-IN"),
    ("mr", "Marathi", "mr", "mr-IN"),
    ("gu", "Gujarati", "gu", "gu-IN"),
    ("kn", "Kannada", "kn", "kn-IN"),
    ("ml", "Malayalam", "ml", "ml-IN"),
    ("pa", "Punjabi", "pa", "pa-IN"),
    ("si", "Sinhala", "si", "si-LK"),
    ("fa", "Persian", "fa", "fa-IR"),
    ("he", "Hebrew", "iw", "he-IL"),
    ("pl", "Polish", "pl", "pl-PL"),
    ("uk", "Ukrainian", "uk", "uk-UA"),
    ("cs", "Czech", "cs", "cs-CZ"),
    ("sv", "Swedish", "sv", "sv-SE"),
    ("no", "Norwegian", "no", "nb-NO"),
    ("da", "Danish", "da", "da-DK"),
    ("fi", "Finnish", "fi", "fi-FI"),
    ("el", "Greek", "el", "el-GR"),
    ("hu", "Hungarian", "hu", "hu-HU"),
    ("ro", "Romanian", "ro", "ro-RO"),
    ("bg", "Bulgarian", "bg", "bg-BG"),
    ("hr", "Croatian", "hr", "hr-HR"),
    ("sr", "Serbian", "sr", "sr-RS"),
    ("am", "Amharic", "am", "am-ET"),
    ("jv", "Javanese", "jw", "jv-ID"),
    ("su", "Sundanese", "su", "su-ID"),
    ("kk", "Kazakh", "kk", "kk-KZ"),
    ("uz", "Uzbek", "uz", "uz-UZ"),
    ("mn", "Mongolian", "mn", "mn-MN"),
    ("ka", "Georgian", "ka", "ka-GE"),
    ("az", "Azerbaijani", "az", "az-AZ"),
    ("ps", "Pashto", "ps", "ps-AF"),
    ("so", "Somali", "so", "so-SO"),
    ("af", "Afrikaans", "af", "af-ZA"),
    ("zu", "Zulu", "zu", "zu-ZA"),
]

BY_CODE = {row[0]: row for row in LANGS}
NAMES = [row[1] for row in LANGS]
NAME_TO_CODE = {row[1]: row[0] for row in LANGS}

# Whisper language codes that differ from ours
WHISPER_TO_CODE = {"zh": "zh-CN", "tl": "fil", "pt": "pt-BR", "jw": "jv", "iw": "he", "haw": "haw"}
# What we pass to Whisper when the user fixes the spoken language
CODE_TO_WHISPER = {"zh-CN": "zh", "zh-TW": "zh", "fil": "tl", "pt-BR": "pt", "pt-PT": "pt", "jv": "jw"}

WHISPER_NAMES = {
    "en": "English", "zh": "Chinese", "yue": "Cantonese", "ms": "Malay", "id": "Indonesian", "ja": "Japanese",
    "ko": "Korean", "th": "Thai", "vi": "Vietnamese", "ar": "Arabic", "hi": "Hindi", "ta": "Tamil", "bn": "Bengali",
    "es": "Spanish", "fr": "French", "de": "German", "pt": "Portuguese", "it": "Italian", "ru": "Russian",
    "tr": "Turkish", "nl": "Dutch", "tl": "Filipino", "my": "Burmese", "km": "Khmer", "lo": "Lao", "ne": "Nepali",
    "ur": "Urdu", "sw": "Swahili",
}


def name(code):
    if code in BY_CODE:
        return BY_CODE[code][1]
    return WHISPER_NAMES.get(code, code or "?")


def from_whisper(wcode):
    return WHISPER_TO_CODE.get(wcode, wcode)


def to_whisper(code, model_size="large-v3"):
    """Whisper language token for a LINGUA code. Cantonese ('yue') only exists in large-v3 models;
    smaller models get Chinese ('zh') instead of an error."""
    if not code or code == "auto" or code.startswith("x-"):
        return None
    w = CODE_TO_WHISPER.get(code, code.split("-")[0])
    if w == "yue" and "large-v3" not in str(model_size):
        return "zh"
    return w


# Groq/OpenAI return the language as an English name ("english", "malay")
_NAME_TO_WHISPER = {v.lower(): k for k, v in WHISPER_NAMES.items()}
_NAME_TO_WHISPER.update({"mandarin": "zh", "tagalog": "tl", "burmese": "my", "myanmar": "my"})


def whisper_name_to_code(name):
    n = (name or "").strip().lower()
    if not n:
        return None
    if n in _NAME_TO_WHISPER:
        return from_whisper(_NAME_TO_WHISPER[n])
    if len(n) <= 3:
        return from_whisper(n)
    return None


def is_cjk_char(t):
    return any("\u3040" <= ch <= "\u30ff" or "\u3400" <= ch <= "\u9fff" or "\uac00" <= ch <= "\ud7af" for ch in t)


def google_code(code):
    return BY_CODE[code][2] if code in BY_CODE else code.split("-")[0]


def tts_locale(code):
    return BY_CODE[code][3] if code in BY_CODE else code


def same_language(src, tgt):
    """True when no translation is needed (Simplified vs Traditional Chinese still counts as different)."""
    if not src or not tgt:
        return False
    if src == tgt:
        return True
    if src.startswith("zh") or tgt.startswith("zh"):
        return False
    return src.split("-")[0] == tgt.split("-")[0]
