"""When is each word said? (2026-10-23, backlog 82, Patch J.) Runs a local speech recogniser (faster-whisper, free, no
API) over the narration mp3 that already exists and returns [(word, start_secs, end_secs)]. Used ONLY to learn the times
of the words that name a room (see word_align.py / scene_timing.plan_from_anchors); the recognised spelling is never used.

Real test on the server (2026-10-23, job 6e3d0d40): 30 s of audio in 7.7 s on CPU, last word ended at 30.26 s for a
30.42 s file. Never raises: any problem returns None and the caller falls back to the previous narration mode.
The audio is decoded with pydub and handed over as an array because the installed 'av' package is too old for
faster-whisper's own file reader (TypeError: open() got an unexpected keyword argument 'metadata_errors').
"""
import logging
import os

log = logging.getLogger("word_timing")

MODEL_SIZE = os.environ.get("PVS_WHISPER_MODEL", "small")
_model = None


def _get_model():
    global _model
    if _model is None:
        from faster_whisper import WhisperModel
        _model = WhisperModel(MODEL_SIZE, device="cpu", compute_type="int8")
    return _model


def transcribe_words(audio_path: str, language: str = "it"):
    """[(word, start, end)] for the audio file, or None when it cannot be done."""
    try:
        import numpy as np
        from pydub import AudioSegment
        seg = AudioSegment.from_file(audio_path).set_frame_rate(16000).set_channels(1).set_sample_width(2)
        audio = np.frombuffer(seg.raw_data, dtype=np.int16).astype(np.float32) / 32768.0
        segments, _info = _get_model().transcribe(audio, language=language, word_timestamps=True, vad_filter=False)
        words = [(w.word.strip(), float(w.start), float(w.end)) for s in segments for w in (s.words or [])]
        if not words:
            log.warning("[WordTiming] the recogniser returned no words")
            return None
        return words
    except Exception as e:
        log.warning(f"[WordTiming] word timing not available: {e}")
        return None
