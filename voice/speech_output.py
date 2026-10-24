"""Text-to-speech — one dedicated worker thread owns the pyttsx3 engine."""

from __future__ import annotations

import logging
import queue
import threading

log = logging.getLogger(__name__)

_STOP_SENTINEL = object()


class SpeechOutput:
    """Single-threaded TTS worker.  speak() is non-blocking; the engine
    is only ever touched from the one worker thread, avoiding COM re-entry
    issues with pyttsx3/SAPI on Windows."""

    def __init__(self) -> None:
        self._q: queue.Queue = queue.Queue()
        self._available = False
        self._speaking = threading.Event()
        # _queued_count tracks messages in the queue but not yet speaking.
        # is_speaking() returns True for both queued and speaking states so
        # the idle-check doesn't restart PTT before TTS has started.
        self._queued_count = 0
        self._queued_lock = threading.Lock()
        self._worker = threading.Thread(target=self._run, daemon=True, name="TTS")
        self._worker.start()

    def _run(self) -> None:
        # SAPI5 (pyttsx3 backend on Windows) lives in a COM STA. Without
        # CoInitialize the thread starts in an unknown apartment and
        # runAndWait() silently hangs after the first call.
        _com_ok = False
        try:
            import pythoncom
            pythoncom.CoInitialize()
            _com_ok = True
        except ImportError:
            pass

        # pyttsx3's runAndWait() returns instantly without speaking on every call after
        # the first on Windows, so prefer the SAPI voice directly (blocking Speak).
        sapi_voice = None
        if _com_ok:
            try:
                import win32com.client
                sapi_voice = win32com.client.Dispatch("SAPI.SpVoice")
                sapi_voice.Rate = 1
                sapi_voice.Volume = 100
            except Exception as exc:
                log.warning("SAPI direct init failed (%s) — falling back to pyttsx3", exc)
                sapi_voice = None

        engine = None
        try:
            if sapi_voice is not None:
                self._available = True
                log.info("TTS engine ready (SAPI direct, COM=%s)", _com_ok)
            else:
                import pyttsx3
                engine = pyttsx3.init()
                engine.setProperty("rate", 160)
                engine.setProperty("volume", 1.0)
                self._available = True
                log.info("TTS engine ready (pyttsx3, COM=%s)", _com_ok)
        except Exception as exc:
            log.warning("TTS init failed: %s — TTS disabled", exc)
            while True:
                item = self._q.get()
                if item is _STOP_SENTINEL:
                    break
            if _com_ok:
                try:
                    import pythoncom
                    pythoncom.CoUninitialize()
                except Exception:
                    pass
            return

        try:
            while True:
                item = self._q.get()
                if item is _STOP_SENTINEL:
                    break
                text: str = item
                with self._queued_lock:
                    self._queued_count = max(0, self._queued_count - 1)
                try:
                    self._speaking.set()
                    log.info("TTS playing: %r", text[:60])
                    if self._speak_localized(text):
                        pass
                    elif sapi_voice is not None:
                        sapi_voice.Speak(text)
                    else:
                        engine.say(text)
                        engine.runAndWait()
                    log.info("TTS done")
                except Exception as exc:
                    log.error("TTS error: %s", exc)
                finally:
                    self._speaking.clear()
        finally:
            if _com_ok:
                try:
                    import pythoncom
                    pythoncom.CoUninitialize()
                except Exception:
                    pass

    @staticmethod
    def _speak_localized(text: str) -> bool:
        """Speak `text` in the current reply language (Urdu/Punjabi). False = caller should use English SAPI."""
        from voice import language, tts_online
        lang = language.get_reply_language()
        if lang == "en" or not tts_online.available():
            return False
        try:
            translated = language.from_english(language.shorten_for_speech(text), lang)
            if not translated:
                return False
            log.info("TTS [%s]: %r", lang, translated[:60])
            tts_online.speak(translated, lang)
            return True
        except Exception as exc:
            log.warning("Localized TTS failed (%s) — falling back to English", exc)
            return False

    def speak(self, text: str) -> None:
        if not text:
            return
        log.info("[TTS] %s", text[:80])
        with self._queued_lock:
            # Drain stale queued items, adjusting the count.
            try:
                while True:
                    self._q.get_nowait()
                    self._queued_count = max(0, self._queued_count - 1)
            except queue.Empty:
                pass
            self._queued_count += 1
        self._q.put(text)

    def stop(self) -> None:
        from voice import tts_online
        tts_online.stop_playback()
        with self._queued_lock:
            try:
                while True:
                    self._q.get_nowait()
                    self._queued_count = max(0, self._queued_count - 1)
            except queue.Empty:
                pass

    def is_speaking(self) -> bool:
        with self._queued_lock:
            queued = self._queued_count > 0
        return self._speaking.is_set() or queued

    def set_rate(self, wpm: int) -> None:
        pass  # rate is set at engine init; dynamic rate changes not yet supported

    def set_voice(self, voice_id: str) -> None:
        pass

    def list_voices(self) -> list[dict]:
        return []


_speech: SpeechOutput | None = None


def get_speech_output() -> SpeechOutput:
    global _speech
    if _speech is None:
        _speech = SpeechOutput()
    return _speech
