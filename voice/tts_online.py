"""Online TTS for Urdu / Punjabi (Google Translate voice via gTTS) played with Windows MCI."""

from __future__ import annotations

import logging
import os
import tempfile
import threading

log = logging.getLogger(__name__)

_ALIAS = "jarvis_tts"
_GTTS_LANG = {"ur": "ur", "pa": "pa"}
_play_lock = threading.Lock()


def available() -> bool:
    try:
        import gtts  # noqa: F401
        import ctypes
        return hasattr(ctypes, "windll")
    except Exception:
        return False


def synthesize(text: str, lang: str) -> str:
    """Write an mp3 for `text` and return its path. Raises on failure."""
    from gtts import gTTS
    fd, path = tempfile.mkstemp(prefix="jarvis_tts_", suffix=".mp3")
    os.close(fd)
    try:
        gTTS(text=text, lang=_GTTS_LANG[lang]).save(path)
    except Exception:
        _remove(path)
        raise
    return path


def _mci(command: str) -> int:
    import ctypes
    return ctypes.windll.winmm.mciSendStringW(command, None, 0, None)


def play_mp3(path: str) -> None:
    """Blocking playback of an mp3 file."""
    with _play_lock:
        _mci(f"close {_ALIAS}")
        err = _mci(f'open "{path}" type mpegvideo alias {_ALIAS}')
        if err:
            raise RuntimeError(f"MCI open failed ({err})")
        try:
            _mci(f"play {_ALIAS} wait")
        finally:
            _mci(f"close {_ALIAS}")


def stop_playback() -> None:
    try:
        _mci(f"stop {_ALIAS}")
    except Exception:
        pass


def speak(text: str, lang: str) -> None:
    path = synthesize(text, lang)
    try:
        play_mp3(path)
    finally:
        _remove(path)


def _remove(path: str) -> None:
    try:
        os.remove(path)
    except OSError:
        pass
