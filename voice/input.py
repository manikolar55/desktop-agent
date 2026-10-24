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

# Phrases Whisper invents when it is fed silence or background noise.
_HALLUCINATIONS = {
    "thank you", "thanks", "thanks for watching", "thank you for watching",
    "you", "bye", "the end", "so", "oh",
}

# Whisper language codes that Urdu/Punjabi speech gets spread across when the model is unsure.
_INDIC_CODES = ("ur", "hi", "pa", "gu", "bn", "te", "ne", "mr", "sa")

_ECHO_TAIL_S = 0.8
_last_talking = 0.0


def _agent_is_talking() -> bool:
    """True while the agent's TTS is playing, and briefly after (speaker echo)."""
    global _last_talking
    try:
        from voice.speech_output import get_speech_output
        if get_speech_output().is_speaking():
            _last_talking = time.monotonic()
            return True
    except Exception:
        return False
    return time.monotonic() - _last_talking < _ECHO_TAIL_S


SAMPLE_RATE = 16_000
CHUNK_MS    = 100          # InputStream block size in ms
CHUNK_FRAMES = int(SAMPLE_RATE * CHUNK_MS / 1000)


class VoiceInput:
    def __init__(self, model_size: str = "base", mic_device: str = "", language: str = "auto") -> None:
        self._model_size = model_size
        self._language_mode = language
        if mic_device and _SOUND_AVAILABLE:
            dev = int(mic_device) if mic_device.strip().isdigit() else mic_device
            sd.default.device = (dev, sd.default.device[1])
            log.info("Microphone device set to %r", dev)
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

                        if _agent_is_talking():
                            # The mic would record the agent's own voice — throw this audio away.
                            chunks.clear()
                            speech_started = False
                            silent_frames = 0
                            speech_frame_run = 0
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

    def listen_long(
        self,
        max_duration: float = 300.0,
        silence_after_speech: float = 4.0,
        progress_callback: Callable[[float], None] | None = None,
    ) -> str:
        """Long-listen mode: records up to max_duration seconds with a longer silence gap.
        Used for dictation, meeting notes, and extended instructions.
        progress_callback(elapsed_seconds) is called every second while recording."""
        if not self._available:
            return ""
        self._load_model()

        audio_q: queue.Queue = queue.Queue()

        def _cb(indata, frames, t, status):
            audio_q.put(indata.copy())

        chunks: list = []
        speech_started = False
        silent_frames = 0
        speech_frame_run = 0
        silence_limit = int(silence_after_speech * 1000 / CHUNK_MS)
        max_chunks = int(max_duration * 1000 / CHUNK_MS)
        elapsed_chunks = 0

        log.info("LongListen: recording (max=%.0fs, silence=%.1fs)", max_duration, silence_after_speech)

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
                        elapsed_chunks += 1

                        if progress_callback and elapsed_chunks % 10 == 0:
                            progress_callback(elapsed_chunks * CHUNK_MS / 1000)

                        if rms > 0.008:
                            speech_frame_run += 1
                            if speech_frame_run >= 2:
                                speech_started = True
                            silent_frames = 0
                        elif speech_started:
                            speech_frame_run = 0
                            silent_frames += 1
                            if silent_frames >= silence_limit:
                                log.info("LongListen: long silence detected — stopping")
                                break
                        else:
                            speech_frame_run = 0

            except Exception as exc:
                log.error("LongListen InputStream error: %s", exc)
                return ""

        if not chunks:
            return ""

        audio = np.concatenate(chunks).flatten()
        duration = len(audio) / SAMPLE_RATE
        log.info("LongListen: captured %.1f s — transcribing…", duration)
        return self._transcribe_long(audio)

    def _transcribe_long(self, audio: "np.ndarray") -> str:
        """Transcribe long audio with settings tuned for extended speech."""
        if not self._model:
            return ""

        rms = float(np.sqrt(np.mean(audio ** 2)))
        if rms < 0.003:
            return ""

        result: list[str] = []
        error: list[Exception] = []

        def _run():
            try:
                segments, _ = self._model.transcribe(
                    audio,
                    language="en",
                    vad_filter=True,
                    vad_parameters=dict(
                        threshold=0.20,
                        min_speech_duration_ms=200,
                        min_silence_duration_ms=1000,
                        speech_pad_ms=600,
                    ),
                    beam_size=3,
                    condition_on_previous_text=True,
                    initial_prompt="Meeting notes. Discussion:",
                )
                text = " ".join(s.text.strip() for s in segments).strip()
                log.info("LongListen transcribed %d chars", len(text))
                result.append(text)
            except Exception as exc:
                error.append(exc)

        t = threading.Thread(target=_run, daemon=True)
        t.start()
        t.join(timeout=120)

        if t.is_alive():
            log.error("Long transcription timed out")
            return ""
        if error:
            log.error("Long transcription error: %s", error[0])
            return ""
        return result[0] if result else ""

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

    def _pick_language(self, audio: "np.ndarray") -> tuple[str, str]:
        """Return (whisper decode language, reply language).

        Whisper `base` cannot tell Punjabi from Urdu/Hindi (probability is spread over hi/te/bn/gu/pa) but
        transcribes both best when decoded as Urdu, so any clearly non-English speech is decoded as 'ur'.
        The reply language is refined later from the text."""
        mode = self._language_mode
        if mode == "en":
            return "en", "en"
        if mode in ("ur", "pa"):
            return "ur", mode
        try:
            from faster_whisper.vad import VadOptions
            _, _, all_probs = self._model.detect_language(
                audio, vad_filter=True, vad_parameters=VadOptions(threshold=0.25)
            )
            probs = dict(all_probs)
        except Exception as exc:
            log.debug("Language detection failed (%s) — assuming English", exc)
            return "en", "en"
        en = probs.get("en", 0.0)
        indic = sum(probs.get(k, 0.0) for k in _INDIC_CODES)
        ur = probs.get("ur", 0.0) + probs.get("hi", 0.0)
        pa = probs.get("pa", 0.0)
        log.info("Language probs: en=%.2f indic=%.2f ur+hi=%.2f pa=%.2f", en, indic, ur, pa)
        if en >= 0.3 or indic < 0.4:
            return "en", "en"
        return "ur", ("pa" if pa > ur else "ur")

    def _transcribe(self, audio: "np.ndarray") -> str:
        if not self._model:
            return ""

        # Skip transcription only if audio is truly inaudible — Whisper VAD handles the rest.
        rms = float(np.sqrt(np.mean(audio ** 2)))
        if rms < 0.004:
            log.debug("Transcribe: skipped (RMS=%.4f too low)", rms)
            return ""

        # Your mic is quiet (RMS ~0.01-0.03): scale peaks to ~0.7 so Whisper hears clearer speech.
        peak = float(np.max(np.abs(audio)))
        if peak > 0:
            audio = (audio * min(0.7 / peak, 20.0)).astype("float32")

        result: list[str] = []
        error: list[Exception] = []

        def _run():
            try:
                lang, reply_lang = self._pick_language(audio)
                segments, info = self._model.transcribe(
                    audio,
                    language=lang,
                    vad_filter=True,
                    vad_parameters=dict(
                        threshold=0.25,               # default 0.5 is too strict — lower catches quiet speech
                        min_speech_duration_ms=100,   # accept very short speech bursts
                        min_silence_duration_ms=600,
                        speech_pad_ms=400,
                    ),
                    beam_size=5,
                    temperature=0.0,
                    condition_on_previous_text=False,
                    initial_prompt=(
                        "Desktop assistant. Commands: open Chrome, open YouTube, open Upwork, "
                        "search Google, close browser, find file, click, type, screenshot, "
                        "open app, what is, explain."
                    ) if lang == "en" else None,
                )
                kept: list[str] = []
                for s in segments:
                    log.info(
                        "Segment %r avg_logprob=%.2f no_speech=%.2f",
                        s.text.strip()[:50], s.avg_logprob, s.no_speech_prob,
                    )
                    if (
                        s.no_speech_prob > 0.6
                        or s.avg_logprob < -1.6
                        or (s.avg_logprob < -1.0 and s.no_speech_prob > 0.5)
                        or s.compression_ratio > 2.4
                    ):
                        log.info("Transcribe: dropped low-confidence segment")
                        continue
                    kept.append(s.text.strip())
                text = " ".join(kept).strip()
                log.info("Transcribe: RMS=%.4f → %r", rms, text[:80])
                if text.lower().strip(" .!?,") in _HALLUCINATIONS:
                    log.info("Transcribe: dropped Whisper hallucination %r", text)
                    text = ""
                if text and lang == "en":
                    from agent.learning import apply_vocab
                    text = apply_vocab(text)
                if text:
                    from voice.language import note_voice
                    note_voice(text, reply_lang)
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
        s = get_settings()
        _voice_input = VoiceInput(
            model_size=s.whisper_model_size, mic_device=s.mic_device, language=s.voice_language
        )
    return _voice_input
