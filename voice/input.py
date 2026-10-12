"""Voice input — faster-whisper + sounddevice InputStream (thread-safe)."""

from __future__ import annotations

import logging
import queue
import threading
import time
from typing import Callable

log = logging.getLogger(__name__)

TranscriptCallback = Callable[[str], None]

try:
    import sounddevice as sd
    import numpy as np
    _SOUND_AVAILABLE = True
except Exception as _e:
    _SOUND_AVAILABLE = False
    log.warning("sounddevice not available — microphone input disabled (%s)", _e)

try:
    from faster_whisper import WhisperModel
    _WHISPER_AVAILABLE = True
except Exception as _e:
    _WHISPER_AVAILABLE = False
    log.warning("faster-whisper not available — voice transcription disabled (%s)", _e)

SAMPLE_RATE = 16_000
CHUNK_MS    = 100          # InputStream block size in ms
CHUNK_FRAMES = int(SAMPLE_RATE * CHUNK_MS / 1000)


class VoiceInput:
    def __init__(self, model_size: str = "base") -> None:
        self._model_size = model_size
        self._model: "WhisperModel | None" = None
        self._callback: TranscriptCallback | None = None
        self._available = _SOUND_AVAILABLE and _WHISPER_AVAILABLE

        # shared lock — only one recording mode active at a time
        self._record_lock = threading.Lock()
        self._stop_wake = threading.Event()
        self._wake_thread: threading.Thread | None = None

    # ── Public ────────────────────────────────────────────────────────────────

    def is_available(self) -> bool:
        return self._available

    def set_callback(self, cb: TranscriptCallback) -> None:
        self._callback = cb

    # ── PTT: click once → speak → silence auto-stops → returns text ───────────

    def listen_and_transcribe(
        self,
        max_duration: float = 30.0,
        silence_threshold: float = 0.010,
        silence_after_speech: float = 1.3,
    ) -> str:
        """Block until the user finishes speaking, return transcript."""
        if not self._available:
            return ""
        self._load_model()

        audio_q: queue.Queue = queue.Queue()

        def _cb(indata, frames, t, status):
            audio_q.put(indata.copy())

        chunks: list = []
        speech_started = False
        silent_frames = 0
        # Require 2 consecutive frames above threshold before declaring speech —
        # prevents single-frame ambient noise spikes from triggering false captures.
        speech_frame_run = 0
        silence_limit = int(silence_after_speech * 1000 / CHUNK_MS)
        max_chunks = int(max_duration * 1000 / CHUNK_MS)

        log.info("PTT: listening (threshold=%.3f, max=%.0fs)", silence_threshold, max_duration)

        with self._record_lock:
            try:
                with sd.InputStream(
                    samplerate=SAMPLE_RATE,
                    channels=1,
                    dtype="float32",
                    blocksize=CHUNK_FRAMES,
                    callback=_cb,
                ):
                    for _ in range(max_chunks):
                        try:
                            block = audio_q.get(timeout=0.5)
                        except queue.Empty:
                            continue

                        rms = float(np.sqrt(np.mean(block ** 2)))
                        chunks.append(block)

                        if rms > silence_threshold:
                            speech_frame_run += 1
                            if speech_frame_run >= 2:
                                speech_started = True
                            silent_frames = 0
                        elif speech_started:
                            speech_frame_run = 0
                            silent_frames += 1
                            if silent_frames >= silence_limit:
                                log.info("PTT: silence detected — stopping")
                                break
                        else:
                            speech_frame_run = 0

            except Exception as exc:
                log.error("PTT InputStream error: %s", exc)
                return ""

        if not chunks:
            return ""

        audio = np.concatenate(chunks).flatten()
        log.info("PTT: captured %.1f s — transcribing…", len(audio) / SAMPLE_RATE)
        return self._transcribe(audio)

    # ── Continuous / wake-word mode ───────────────────────────────────────────

    def start_listening(self) -> None:
        """Start continuous background listener (wake-word mode)."""
        if not self._available:
            log.warning("Voice input not available")
            return
        if self._wake_thread and self._wake_thread.is_alive():
            return
        self._load_model()
        self._stop_wake.clear()
        self._wake_thread = threading.Thread(
            target=self._wake_worker, daemon=True, name="WakeWordListener"
        )
        self._wake_thread.start()
        log.info("Wake-word listener started (model=%s)", self._model_size)

    def stop_listening(self) -> None:
        self._stop_wake.set()
        log.info("Wake-word listener stopping")

    def _wake_worker(self) -> None:
        """Collect 3-second windows and transcribe each one."""
        collect_secs = 3.0
        collect_chunks = int(collect_secs * 1000 / CHUNK_MS)
        audio_q: queue.Queue = queue.Queue()

        def _cb(indata, frames, t, status):
            audio_q.put(indata.copy())

        log.info("WakeWord: InputStream open")
        try:
            with sd.InputStream(
                samplerate=SAMPLE_RATE,
                channels=1,
                dtype="float32",
                blocksize=CHUNK_FRAMES,
                callback=_cb,
            ):
                while not self._stop_wake.is_set():
                    buf: list = []
                    for _ in range(collect_chunks):
                        if self._stop_wake.is_set():
                            break
                        try:
                            block = audio_q.get(timeout=0.4)
                            buf.append(block)
                        except queue.Empty:
                            pass

                    if not buf or self._stop_wake.is_set():
                        continue

                    audio = np.concatenate(buf).flatten()
                    rms = float(np.sqrt(np.mean(audio ** 2)))
                    log.debug("WakeWord: RMS=%.4f (%.1f s)", rms, len(audio) / SAMPLE_RATE)

                    if rms < 0.005:
                        # near-silent — skip transcription to save CPU
                        continue

                    text = self._transcribe(audio)
                    log.info("WakeWord: transcribed %r", text)
                    if text and self._callback:
                        self._callback(text)

        except Exception as exc:
            log.error("WakeWord InputStream error: %s", exc)

    # ── Model ─────────────────────────────────────────────────────────────────

    def _load_model(self) -> None:
        if self._model is None and _WHISPER_AVAILABLE:
            log.info("Loading Whisper model '%s'…", self._model_size)
            self._model = WhisperModel(self._model_size, compute_type="int8")
            log.info("Whisper model loaded")

    def _transcribe(self, audio: "np.ndarray") -> str:
        if not self._model:
            return ""

        # Skip transcription only if audio is truly inaudible — Whisper VAD handles the rest.
        rms = float(np.sqrt(np.mean(audio ** 2)))
        if rms < 0.004:
            log.debug("Transcribe: skipped (RMS=%.4f too low)", rms)
            return ""

        result: list[str] = []
        error: list[Exception] = []

        def _run():
            try:
                segments, info = self._model.transcribe(
                    audio,
                    language="en",
                    vad_filter=True,
                    vad_parameters=dict(
                        min_silence_duration_ms=600,  # keep pauses < 600 ms
                        speech_pad_ms=400,            # pad around speech so edges aren't cut
                    ),
                    beam_size=1,
                    condition_on_previous_text=False,
                    initial_prompt=(
                        "Desktop assistant. Commands: open Chrome, Upwork, close browser, "
                        "search web, click, type, screenshot, open app."
                    ),
                )
                text = " ".join(s.text.strip() for s in segments).strip()
                log.info("Transcribe: RMS=%.4f → %r", rms, text[:80])
                result.append(text)
            except Exception as exc:
                error.append(exc)

        t = threading.Thread(target=_run, daemon=True)
        t.start()
        t.join(timeout=15)

        if t.is_alive():
            log.error("Transcription timed out after 15s — skipping")
            return ""
        if error:
            log.error("Transcription error: %s", error[0])
            return ""
        return result[0] if result else ""

    # ── Back-compat stubs ─────────────────────────────────────────────────────

    CHUNK_SECONDS = 5

    def transcribe_once(self, duration_seconds: float = 5.0) -> str:
        return self.listen_and_transcribe(max_duration=duration_seconds)

    def start_ptt(self) -> None:
        pass

    def stop_ptt(self) -> str:
        return ""


_voice_input: VoiceInput | None = None


def get_voice_input() -> VoiceInput:
    global _voice_input
    if _voice_input is None:
        from config.settings import get_settings
        _voice_input = VoiceInput(model_size=get_settings().whisper_model_size)
    return _voice_input
