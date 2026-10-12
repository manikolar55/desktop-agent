"""Wake-word detection stub — push-to-talk is the primary activation method."""

from __future__ import annotations

import logging
import threading
from typing import Callable

log = logging.getLogger(__name__)

WakeCallback = Callable[[], None]

WAKE_PHRASES = {"hey assistant", "ok assistant", "assistant"}


class WakeWordDetector:
    """
    Lightweight keyword spotter built on top of the Whisper transcription pipeline.
    A full openWakeWord integration would improve latency; this implementation
    listens in short bursts and checks for wake phrases in the transcript.

    Status: partially_supported (functional but higher latency than a dedicated model)
    """

    def __init__(self) -> None:
        self._callback: WakeCallback | None = None
        self._active = threading.Event()
        self._thread: threading.Thread | None = None

    def set_callback(self, cb: WakeCallback) -> None:
        self._callback = cb

    def start(self) -> None:
        try:
            from voice.input import get_voice_input
            vi = get_voice_input()
            if not vi.is_available():
                log.warning("Wake word detector: voice input unavailable")
                return
        except Exception:
            return
        self._active.set()
        self._thread = threading.Thread(target=self._worker, daemon=True, name="WakeWord")
        self._thread.start()
        log.info("Wake-word detector started")

    def stop(self) -> None:
        self._active.clear()

    def _worker(self) -> None:
        from voice.input import get_voice_input
        vi = get_voice_input()
        while self._active.is_set():
            try:
                text = vi.transcribe_once(duration_seconds=2.0).lower()
                if any(phrase in text for phrase in WAKE_PHRASES):
                    log.info("Wake word detected: %s", text)
                    if self._callback:
                        self._callback()
            except Exception as exc:
                log.debug("Wake word error: %s", exc)
