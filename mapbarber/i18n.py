"""User interface strings, loaded from locales/<code>.json."""
import json
import locale
import os

LOCALE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "locales")
LANGUAGES = {"en": "English", "ko": "한국어", "ja": "日本語", "zh": "简体中文", "de": "Deutsch", "es": "Español"}
_tables = {}


def table(code):
    if code not in _tables:
        with open(os.path.join(LOCALE_DIR, f"{code}.json"), encoding="utf-8") as f:
            _tables[code] = json.load(f)
    return _tables[code]


def system_language():
    try:
        code = (locale.getlocale()[0] or os.environ.get("LANG", ""))[:2].lower()
    except ValueError:
        code = ""
    return code if code in LANGUAGES else "en"


class Translator:
    def __init__(self, language=None):
        self.language = language if language in LANGUAGES else system_language()

    def __call__(self, key, **values):
        text = table(self.language).get(key) or table("en").get(key)
        if text is None:
            return key
        return text.format(**values) if values else text
