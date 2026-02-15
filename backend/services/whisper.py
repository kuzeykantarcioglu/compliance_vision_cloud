"""Whisper Service — extract audio from video and transcribe with OpenAI Whisper.

Pipeline:
  1. Extract audio track from video using ffmpeg (→ temp .wav file)
  2. Send audio to OpenAI Whisper API (whisper-1 model)
  3. Return timestamped transcript segments

Audio extraction runs locally (ffmpeg), transcription is an API call.
The two are sequential — we need the audio file before transcribing.
"""

import os
import subprocess
import tempfile
import logging

from backend.core.config import openai_client as client
from backend.models.schemas import TranscriptSegment, TranscriptResult

logger = logging.getLogger(__name__)


def extract_audio(video_path: str) -> str | None:
    """Extract audio track from video as a WAV file using ffmpeg.

    Returns path to temp WAV file, or None if video has no audio track.
    """
    # Create temp file for audio
    fd, audio_path = tempfile.mkstemp(suffix=".wav")
    os.close(fd)

    cmd = [
        "ffmpeg",
        "-i", video_path,
        "-vn",                    # No video
        "-acodec", "pcm_s16le",   # WAV format (Whisper likes WAV)
        "-ar", "16000",           # 16kHz sample rate (Whisper optimal)
        "-ac", "1",               # Mono
        "-y",                     # Overwrite
        audio_path,
    ]

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=60,
        )
        if result.returncode != 0:
            logger.warning(f"ffmpeg exited with code {result.returncode}: {result.stderr[:500]}")
        # Check if output file has content (some videos have no audio)
        if os.path.exists(audio_path) and os.path.getsize(audio_path) > 1000:
            logger.info(f"Audio extracted: {os.path.getsize(audio_path)} bytes")
            return audio_path
        else:
            logger.info(
                f"No usable audio track — file {'exists' if os.path.exists(audio_path) else 'missing'}"
                f", size={os.path.getsize(audio_path) if os.path.exists(audio_path) else 0}"
            )
            if os.path.exists(audio_path):
                os.unlink(audio_path)
            return None
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as e:
        logger.warning(f"Audio extraction failed: {e}")
        if os.path.exists(audio_path):
            os.unlink(audio_path)
        return None


async def transcribe_audio(audio_path: str) -> TranscriptResult:
    """Transcribe audio file using OpenAI Whisper API.

    Uses the verbose_json response format to get word-level timestamps.

    Args:
        audio_path: Path to WAV/MP3/etc audio file.

    Returns:
        TranscriptResult with full text and timestamped segments.
    """
    with open(audio_path, "rb") as audio_file:
        response = await client.audio.transcriptions.create(
            model="whisper-1",
            file=audio_file,
            response_format="verbose_json",
            timestamp_granularities=["segment"],
        )

    segments = []
    if hasattr(response, "segments") and response.segments:
        for seg in response.segments:
            segments.append(TranscriptSegment(
                start=seg.get("start", seg.start) if hasattr(seg, "start") else seg.get("start", 0),
                end=seg.get("end", seg.end) if hasattr(seg, "end") else seg.get("end", 0),
                text=seg.get("text", seg.text) if hasattr(seg, "text") else seg.get("text", ""),
            ))

    full_text = response.text if hasattr(response, "text") else ""

    return TranscriptResult(
        full_text=full_text.strip(),
        segments=segments,
        language=response.language if hasattr(response, "language") else "unknown",
        duration=response.duration if hasattr(response, "duration") else 0.0,
    )


async def transcribe_video(video_path: str) -> TranscriptResult | None:
    """Full pipeline: extract audio from video, then transcribe.

    Returns None if video has no audio track.
    """
    audio_path = extract_audio(video_path)
    if not audio_path:
        logger.info("No audio track found in video, skipping transcription.")
        return None

    try:
        result = await transcribe_audio(audio_path)
        return result
    finally:
        # Clean up temp audio file
        if os.path.exists(audio_path):
            os.unlink(audio_path)
