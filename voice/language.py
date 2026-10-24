"""Language detection, translation and reply-language state for English / Urdu / Punjabi."""

from __future__ import annotations

import logging
import re
import threading

log = logging.getLogger(__name__)

SUPPORTED = ("en", "ur", "pa")
LANGUAGE_NAMES = {"en": "English", "ur": "Urdu", "pa": "Punjabi"}

_lock = threading.Lock()
_reply_lang = "en"
_last_voice: dict = {"text": "", "lang": "en"}
_translation_cache: dict[tuple[str, str], str] = {}

_ROMAN_URDU_MARKERS = {
    "kya", "hai", "hain", "mujhe", "mujhay", "mera", "meri", "mere", "kholo", "kholdo",
    "karo", "kardo", "dikhao", "batao", "bata", "mein", "nahi", "nahin", "abhi", "phir",
    "chalao", "likho", "bhejo", "dhoondo", "kahan", "kidhar", "kaise", "kyun", "kitna",
    "kaun", "aap", "tum", "apna", "apni", "wala", "wali", "jaldi", "shuru", "lagao",
    "suno", "dekho", "thora", "zara", "shukriya", "acha", "theek", "sab", "kuch",
}


def script_of(text: str) -> str:
    arabic = gurmukhi = latin = 0
    for ch in text:
        o = ord(ch)
        if 0x0600 <= o <= 0x06FF or 0x0750 <= o <= 0x077F or 0xFB50 <= o <= 0xFDFF or 0xFE70 <= o <= 0xFEFF:
            arabic += 1
        elif 0x0A00 <= o <= 0x0A7F:
            gurmukhi += 1
        elif ch.isascii() and ch.isalpha():
            latin += 1
    if gurmukhi and gurmukhi >= arabic:
        return "gurmukhi"
    if arabic and arabic >= latin // 2:
        return "arabic"
    return "latin"


def looks_like_roman_urdu(text: str) -> bool:
    words = re.findall(r"[a-z]+", text.lower())
    if not words:
        return False
    hits = len({w for w in words if w in _ROMAN_URDU_MARKERS})
    return hits >= 2 or (hits >= 1 and len(words) <= 3)


def detect_text_language(text: str, hint: str | None = None) -> str:
    """Language of an instruction. `hint` is the language Whisper detected for this utterance."""
    s = script_of(text)
    if s == "gurmukhi":
        return "pa"
    if s == "arabic":
        return hint if hint in ("ur", "pa") else "ur"
    if hint in ("ur", "pa"):
        return hint
    if looks_like_roman_urdu(text):
        return "ur"
    return "en"


def note_voice(text: str, lang: str) -> None:
    with _lock:
        _last_voice["text"] = text
        _last_voice["lang"] = lang


def voice_hint(text: str) -> str | None:
    with _lock:
        return _last_voice["lang"] if _last_voice["text"] == text else None


def get_reply_language() -> str:
    with _lock:
        return _reply_lang


def set_reply_language(lang: str) -> None:
    global _reply_lang
    with _lock:
        _reply_lang = lang if lang in SUPPORTED else "en"


def shorten_for_speech(text: str, limit: int = 160) -> str:
    """Keep whole sentences up to `limit` chars so translated speech doesn't run for a minute."""
    if len(text) <= limit:
        return text
    out = ""
    for sentence in re.split(r"(?<=[.!?])\s+", text):
        if out and len(out) + len(sentence) + 1 > limit:
            break
        out = f"{out} {sentence}".strip()
    return out[:limit] if len(out) > limit else out


def _complete(system: str, user: str, max_tokens: int) -> str:
    from models.provider import get_provider
    return get_provider().complete(system, user, max_tokens=max_tokens).strip()


def to_english(text: str, lang: str, refine: bool = False) -> tuple[str, str]:
    """Translate a spoken/typed command into an English instruction.

    Returns (english, language). With refine=True the model also decides whether the speaker used Urdu or
    Punjabi (speech recognition can't tell them apart). On failure returns (text, lang) unchanged."""
    system = (
        f"You translate a spoken command for a computer assistant from {LANGUAGE_NAMES.get(lang, 'Urdu')} "
        "into short, natural English. The text may be an imperfect speech transcript (Punjabi speech is often "
        "transcribed in Urdu script), may be written in Roman letters (e.g. 'Chrome kholo'), and may mix in "
        "English words. Keep app and website names in English (Chrome, YouTube, WhatsApp, Notepad).\n"
        "NEVER invent details: do not add apps, websites, or actions that are not clearly present in the text. "
        "If the transcript is too garbled to tell what the user wants, answer ENGLISH: UNCLEAR.\n"
        "Reply in exactly this format:\n"
        "LANG: Urdu or Punjabi (answer Punjabi ONLY if there are clearly Punjabi-specific words or Gurmukhi "
        "script; otherwise Urdu)\n"
        "ENGLISH: <the English instruction, or UNCLEAR>"
    )
    try:
        raw = _complete(system, text, 150)
    except Exception as exc:
        log.warning("to_english failed: %s", exc)
        return text, lang
    m = re.search(r"ENGLISH:\s*(.+)", raw, re.DOTALL)
    english = (m.group(1) if m else raw).strip().strip('"').strip()
    if not english:
        return text, lang
    if refine:
        lm = re.search(r"LANG:\s*(\w+)", raw)
        if lm and lm.group(1).lower() in ("urdu", "punjabi"):
            lang = "pa" if lm.group(1).lower() == "punjabi" else "ur"
    return english, lang


def from_english(text: str, lang: str) -> str | None:
    """Translate an English reply into the target language. Returns None on failure."""
    if lang == "en" or not text.strip():
        return text
    key = (lang, text)
    cached = _translation_cache.get(key)
    if cached:
        return cached
    if lang == "pa":
        target = "Punjabi written in Gurmukhi script"
    else:
        target = "Urdu written in Urdu (Arabic) script, not Roman letters"
    system = (
        f"Translate the assistant reply into {target}. It will be read aloud by a text-to-speech voice, "
        "so use natural spoken phrasing. Keep app, website, file and product names (Chrome, YouTube, "
        "WhatsApp) in their original English form. Return ONLY the translation, nothing else."
    )
    try:
        out = _complete(system, text, 400).strip('"').strip()
    except Exception as exc:
        log.warning("from_english failed: %s", exc)
        return None
    if not out:
        return None
    if len(_translation_cache) > 200:
        _translation_cache.clear()
    _translation_cache[key] = out
    return out
