"""Pydantic models for the entire pipeline.

Data flows:  Policy + Video → FrameObservation[] → Verdict[] → Report
"""

from pydantic import BaseModel, Field
from typing import Optional


# ---------------------------------------------------------------------------
# Policy (input from user)
# ---------------------------------------------------------------------------

class PolicyRule(BaseModel):
    type: str = Field(
        ...,
        description='Rule category: "badge", "ppe", "presence", "action", "environment", "custom"',
    )
    description: str = Field(
        ...,
        description='What to check, e.g. "All persons must wear a green badge"',
    )
    severity: str = Field(
        default="high",
        description='Impact level: "low", "medium", "high", "critical"',
    )


class ReferenceImage(BaseModel):
    id: Optional[str] = Field(
        default=None,
        description="Unique id for referencing in policy; generated on creation",
    )
    label: str = Field(
        ...,
        description='What this image represents, e.g. "Approved badge design", "Authorized person: John"',
    )
    image_base64: str = Field(
        ...,
        description="Base64-encoded JPEG/PNG of the reference image",
    )
    match_mode: str = Field(
        default="must_match",
        description='"must_match" = only this is allowed. "must_not_match" = this should NOT be present.',
    )
    category: str = Field(
        default="objects",
        description='Category: "people", "badges", or "objects"',
    )
    checks: list[str] = Field(
        default_factory=list,
        description='Per-reference compliance checks, e.g. ["Is this person present in the frame?", "Are they wearing a hard hat?"]',
    )


class Policy(BaseModel):
    rules: list[PolicyRule] = Field(default_factory=list)
    custom_prompt: str = Field(
        default="",
        description="Free-form natural language additions to the policy",
    )
    include_audio: bool = Field(
        default=False,
        description="Whether to transcribe and analyze audio from the video",
    )
    reference_images: list[ReferenceImage] = Field(
        default_factory=list,
        description="Visual reference images for comparison (badge designs, authorized persons, etc.)",
    )
    enabled_reference_ids: list[str] = Field(
        default_factory=list,
        description="IDs of references to check. Only these are sent to the VLM. Empty = no references checked.",
    )


# ---------------------------------------------------------------------------
# VLM output (per keyframe)
# ---------------------------------------------------------------------------

class FrameObservation(BaseModel):
    timestamp: float = Field(..., description="Seconds into the video")
    description: str = Field(..., description="VLM text description of the frame")
    trigger: str = Field(
        ...,
        description='Why this frame was captured: "change", "max_gap", "first", "last"',
    )
    change_score: float = Field(default=0.0, description="Change detection score 0-1")
    image_base64: str = Field(
        default="",
        description="Base64-encoded keyframe image (evidence screenshot)",
    )


# ---------------------------------------------------------------------------
# Policy evaluation output
# ---------------------------------------------------------------------------

class Verdict(BaseModel):
    rule_type: str
    rule_description: str
    compliant: bool
    severity: str
    reason: str
    timestamp: Optional[float] = Field(
        default=None,
        description="When the violation was first observed (seconds)",
    )


# ---------------------------------------------------------------------------
# Whisper transcript
# ---------------------------------------------------------------------------

class TranscriptSegment(BaseModel):
    start: float = Field(..., description="Start time in seconds")
    end: float = Field(..., description="End time in seconds")
    text: str = Field(..., description="Transcribed text for this segment")


class TranscriptResult(BaseModel):
    full_text: str = Field(default="", description="Full transcription text")
    segments: list[TranscriptSegment] = Field(default_factory=list)
    language: str = Field(default="unknown")
    duration: float = Field(default=0.0, description="Audio duration in seconds")


# ---------------------------------------------------------------------------
# Final report
# ---------------------------------------------------------------------------

class Report(BaseModel):
    video_id: str
    summary: str
    overall_compliant: bool
    incidents: list[Verdict] = Field(
        default_factory=list,
        description="Non-compliant verdicts only",
    )
    all_verdicts: list[Verdict] = Field(
        default_factory=list,
        description="Every verdict (compliant + non-compliant)",
    )
    recommendations: list[str] = Field(default_factory=list)
    frame_observations: list[FrameObservation] = Field(default_factory=list)
    transcript: Optional[TranscriptResult] = Field(
        default=None,
        description="Whisper transcript (if audio analysis was enabled)",
    )
    analyzed_at: str = Field(..., description="ISO timestamp of analysis")
    total_frames_analyzed: int = 0
    video_duration: float = 0.0


# ---------------------------------------------------------------------------
# API request / response
# ---------------------------------------------------------------------------

class AnalyzeRequest(BaseModel):
    """Policy sent as JSON alongside the video file upload."""
    policy: Policy


class AnalyzeResponse(BaseModel):
    status: str = Field(..., description='"complete" or "error"')
    report: Optional[Report] = None
    error: Optional[str] = None


# ---------------------------------------------------------------------------
# Video processing intermediate result
# ---------------------------------------------------------------------------

class KeyframeData(BaseModel):
    """One keyframe extracted by change detection, with base64 image attached."""
    timestamp: float
    frame_number: int
    change_score: float
    trigger: str
    keyframe_path: str
    image_base64: str = Field(
        default="",
        description="Base64-encoded JPEG, resized to max 512px wide",
    )


class VideoProcessingResult(BaseModel):
    video_id: str
    metadata: dict
    keyframes: list[KeyframeData]
