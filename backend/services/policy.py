"""Policy Evaluation + Report Generation Service.

Single LLM call that takes VLM observations + policy rules and produces
a full structured compliance report. Uses GPT-4o-mini with structured
output (JSON schema) for reliable parsing.

Merging policy eval + report generation into one call saves ~30% latency
and one full API round-trip vs doing them separately.
"""

import json
import logging
from datetime import datetime, timezone

from openai import AsyncOpenAI

from backend.core.config import OPENAI_API_KEY
from backend.models.schemas import (
    FrameObservation,
    KeyframeData,
    PersonSummary,
    Policy,
    Report,
    TranscriptResult,
    Verdict,
)

logger = logging.getLogger(__name__)
client = AsyncOpenAI(api_key=OPENAI_API_KEY)

SYSTEM_PROMPT = """You are an expert compliance evaluator for a video surveillance monitoring system.

You will receive:
1. Visual observations from video frames (with timestamps), including per-person tracking data
2. A compliance policy with rules (each with a FREQUENCY requirement)
3. Optionally, an audio transcript
4. Optionally, PRIOR CONTEXT about rules already satisfied in earlier monitoring chunks

Your job:
- Evaluate EACH policy rule against ALL observations AND the transcript (if provided)
- For each rule, determine: compliant or non-compliant
- Provide clear, concise reasoning citing specific timestamps
- Generate a brief executive summary (1-2 sentences max)
- Provide actionable recommendations (short bullet points)
- Track each identified person individually

FREQUENCY SEMANTICS:
- "ALWAYS": Must hold in EVERY frame. Person must be compliant every time they appear.
- "AT LEAST ONCE": Satisfied if observed in ANY frame. Once satisfied, stays compliant permanently.
- "AT LEAST N TIMES": Satisfied if observed in N or more distinct frames.

CRITICAL — PRIOR CONTEXT:
If prior context states that a rule was ALREADY SATISFIED by a person in an earlier chunk, that person is COMPLIANT for that rule. Do NOT re-flag it as a violation. Mark it compliant with a note like "Previously satisfied."

PER-PERSON EVALUATION:
- Evaluate each person individually against person-relevant rules.
- Produce a person_summaries array with one entry per tracked person.
- If a person was already marked compliant in prior context, keep them compliant.

WRITING STYLE:
- Be concise and direct. No filler words.
- Summary: 1-2 sentences. State # violations and key finding.
- Reasons: 1-2 sentences max. Cite timestamp. No repetition.
- Recommendations: Short action items, not paragraphs.
- Person descriptions: Brief. Focus on compliance-relevant details.

If evidence is ambiguous, note it but still make a call.
If no relevant activity was observed for a rule, mark compliant.

Severity levels: "low", "medium", "high", "critical"
"""

# JSON schema for OpenAI structured output
REPORT_SCHEMA = {
    "type": "object",
    "properties": {
        "summary": {
            "type": "string",
            "description": "Executive summary: how many violations, overall status, key findings. 2-3 sentences.",
        },
        "overall_compliant": {
            "type": "boolean",
            "description": "True if ALL rules are compliant, false if ANY rule is non-compliant.",
        },
        "verdicts": {
            "type": "array",
            "description": "One verdict per policy rule.",
            "items": {
                "type": "object",
                "properties": {
                    "rule_type": {"type": "string"},
                    "rule_description": {"type": "string"},
                    "compliant": {"type": "boolean"},
                    "severity": {"type": "string", "enum": ["low", "medium", "high", "critical"]},
                    "reason": {
                        "type": "string",
                        "description": "Specific reasoning citing timestamps and observations.",
                    },
                    "timestamp": {
                        "type": ["number", "null"],
                        "description": "Timestamp (seconds) of the first observed violation, or null if compliant.",
                    },
                },
                "required": ["rule_type", "rule_description", "compliant", "severity", "reason", "timestamp"],
                "additionalProperties": False,
            },
        },
        "recommendations": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Actionable recommendations to address violations. 1-5 items.",
        },
        "person_summaries": {
            "type": "array",
            "description": "One entry per tracked person across all frames. Empty if no people were identified.",
            "items": {
                "type": "object",
                "properties": {
                    "person_id": {"type": "string", "description": "Consistent ID like Person_A"},
                    "appearance": {"type": "string", "description": "Brief appearance description"},
                    "first_seen": {"type": "number", "description": "Timestamp of first appearance"},
                    "last_seen": {"type": "number", "description": "Timestamp of last appearance"},
                    "frames_seen": {"type": "integer", "description": "Number of frames this person appeared in"},
                    "compliant": {"type": "boolean", "description": "Overall compliance status for this person"},
                    "violations": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Rule descriptions this person violated (empty if compliant)",
                    },
                },
                "required": ["person_id", "appearance", "first_seen", "last_seen", "frames_seen", "compliant", "violations"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["summary", "overall_compliant", "verdicts", "recommendations", "person_summaries"],
    "additionalProperties": False,
}


def _format_observations(observations: list[FrameObservation]) -> str:
    """Format VLM observations into a readable block for the LLM."""
    lines = []
    for obs in observations:
        trigger_tag = f"[{obs.trigger}]" if obs.trigger != "change" else ""
        lines.append(f"[t={obs.timestamp:.1f}s] {trigger_tag} {obs.description}")
        # Include per-person tracking data
        if obs.people:
            for p in obs.people:
                lines.append(f"    - {p.person_id} ({p.appearance}): {p.details}")
    return "\n".join(lines)


def _format_frequency(rule) -> str:
    """Format frequency requirement for display."""
    freq = getattr(rule, "frequency", "always") or "always"
    if freq == "at_least_once":
        return "AT LEAST ONCE"
    elif freq == "at_least_n":
        count = getattr(rule, "frequency_count", 1) or 1
        return f"AT LEAST {count} TIMES"
    return "ALWAYS"


def _format_policy(policy: Policy) -> str:
    """Format the policy into a readable block for the LLM."""
    lines = ["COMPLIANCE POLICY RULES:"]
    for i, rule in enumerate(policy.rules, 1):
        freq_tag = _format_frequency(rule)
        lines.append(f"  {i}. [{rule.severity.upper()}] [{freq_tag}] ({rule.type}) {rule.description}")
    if policy.custom_prompt:
        lines.append(f"\nADDITIONAL POLICY CONTEXT: {policy.custom_prompt}")
    return "\n".join(lines)


def _format_transcript(transcript: TranscriptResult | None) -> str:
    """Format transcript into a readable block for the LLM."""
    if not transcript or not transcript.full_text:
        return ""

    lines = [f"AUDIO TRANSCRIPT (language: {transcript.language}, duration: {transcript.duration:.1f}s):"]
    if transcript.segments:
        for seg in transcript.segments:
            lines.append(f"  [{seg.start:.1f}s - {seg.end:.1f}s] {seg.text.strip()}")
    else:
        lines.append(f"  {transcript.full_text}")
    return "\n".join(lines)


async def evaluate_and_report(
    observations: list[FrameObservation],
    policy: Policy,
    video_id: str,
    video_duration: float = 0.0,
    transcript: TranscriptResult | None = None,
    prior_context: str = "",
) -> Report:
    """Evaluate observations against policy and generate a structured report.

    Single LLM call using GPT-4o-mini with structured output.

    Args:
        observations: VLM frame observations.
        policy: Compliance policy with rules.
        video_id: ID of the analyzed video.
        video_duration: Duration of the video in seconds.
        transcript: Optional Whisper transcript with timestamped segments.
        prior_context: Context from earlier monitoring chunks about already-satisfied rules.

    Returns:
        Report with verdicts, summary, and recommendations.
    """
    obs_text = _format_observations(observations)
    policy_text = _format_policy(policy)
    transcript_text = _format_transcript(transcript)

    user_prompt = f"""{policy_text}

VIDEO OBSERVATIONS ({len(observations)} frames analyzed, {video_duration:.1f}s total):
{obs_text}"""

    if transcript_text:
        user_prompt += f"""

{transcript_text}"""

    if prior_context:
        user_prompt += f"""

PRIOR CONTEXT (from earlier monitoring chunks — rules already satisfied):
{prior_context}"""

    user_prompt += """

Evaluate each policy rule against these observations""" + (
        " and the audio transcript" if transcript_text else ""
    ) + ". Produce a compliance report. Be concise."

    response = await client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
        response_format={
            "type": "json_schema",
            "json_schema": {
                "name": "compliance_report",
                "strict": True,
                "schema": REPORT_SCHEMA,
            },
        },
        temperature=0.1,
        max_tokens=1200,  # Reduced — we want concise reports
    )

    raw = response.choices[0].message.content or "{}"

    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        # Fallback: return error report
        return Report(
            video_id=video_id,
            summary="Failed to parse compliance report from LLM.",
            overall_compliant=False,
            incidents=[],
            all_verdicts=[],
            recommendations=["Retry analysis or check LLM output."],
            frame_observations=observations,
            transcript=transcript,
            analyzed_at=datetime.now(timezone.utc).isoformat(),
            total_frames_analyzed=len(observations),
            video_duration=video_duration,
        )

    # Parse verdicts
    all_verdicts = []
    incidents = []
    for v in data.get("verdicts", []):
        verdict = Verdict(
            rule_type=v.get("rule_type", "unknown"),
            rule_description=v.get("rule_description", ""),
            compliant=v.get("compliant", True),
            severity=v.get("severity", "medium"),
            reason=v.get("reason", ""),
            timestamp=v.get("timestamp"),
        )
        all_verdicts.append(verdict)
        if not verdict.compliant:
            incidents.append(verdict)

    # Parse person summaries
    person_summaries = []
    for ps in data.get("person_summaries", []):
        person_summaries.append(PersonSummary(
            person_id=ps.get("person_id", "Unknown"),
            appearance=ps.get("appearance", ""),
            first_seen=ps.get("first_seen", 0.0),
            last_seen=ps.get("last_seen", 0.0),
            frames_seen=ps.get("frames_seen", 1),
            compliant=ps.get("compliant", True),
            violations=ps.get("violations", []),
            thumbnail_base64="",  # Filled in by the router
        ))

    return Report(
        video_id=video_id,
        summary=data.get("summary", "No summary generated."),
        overall_compliant=data.get("overall_compliant", True),
        incidents=incidents,
        all_verdicts=all_verdicts,
        recommendations=data.get("recommendations", []),
        frame_observations=observations,
        person_summaries=person_summaries,
        transcript=transcript,
        analyzed_at=datetime.now(timezone.utc).isoformat(),
        total_frames_analyzed=len(observations),
        video_duration=video_duration,
    )


# ---------------------------------------------------------------------------
# Combined single-call analysis (VLM + Policy in one shot) — for webcam chunks
# ---------------------------------------------------------------------------

COMBINED_PROMPT = """You are a compliance monitoring AI. You will see surveillance camera frames and a compliance policy.

YOUR JOB: Look at the images, identify what each person is doing, and evaluate each policy rule.

RULES:
- "ALWAYS": Must hold in EVERY frame.
- "AT LEAST ONCE": Satisfied if observed in ANY single frame. Once satisfied, compliant forever.

If PRIOR CONTEXT says a rule was already satisfied, mark it COMPLIANT immediately.

If REFERENCE IMAGES of people are provided, identify people by their reference label.
For unknown people, use "Person_A", "Person_B", etc.

Be CONCISE. Summary: 1 sentence. Reasons: 1 sentence max."""


async def analyze_and_evaluate_combined(
    keyframes: list[KeyframeData],
    policy: Policy,
    video_id: str,
    video_duration: float = 0.0,
    prior_context: str = "",
    reference_images: list = None,
) -> Report:
    """Single-call analysis: send frames + policy to one LLM call, get report back.

    Combines VLM observation + policy evaluation into one API round-trip.
    Much faster than the two-step pipeline for short webcam chunks.
    """
    # Build multimodal content
    content = []

    # Policy rules
    policy_text = _format_policy(policy)
    text = f"{policy_text}\n\nAnalyze the following {len(keyframes)} surveillance frame(s)."

    if prior_context:
        text += f"\n\nPRIOR CONTEXT (rules already satisfied — mark COMPLIANT):\n{prior_context}"

    content.append({"type": "text", "text": text})

    # Add reference images if any
    refs = reference_images or []
    for i, ref in enumerate(refs):
        content.append({"type": "text", "text": f"[REFERENCE: {ref.label}]"})
        mime = "image/png" if ref.image_base64[:4] == "iVBO" else "image/jpeg"
        content.append({
            "type": "image_url",
            "image_url": {"url": f"data:{mime};base64,{ref.image_base64}", "detail": "auto"},
        })

    if refs:
        content.append({"type": "text", "text": "[SURVEILLANCE FRAMES BELOW]"})

    # Add keyframe images with timestamps
    for kf in keyframes:
        content.append({"type": "text", "text": f"[Frame at t={kf.timestamp:.1f}s]"})
        content.append({
            "type": "image_url",
            "image_url": {"url": f"data:image/jpeg;base64,{kf.image_base64}", "detail": "auto"},
        })

    logger.info(f"Combined analysis: {len(keyframes)} frames, {len(policy.rules)} rules")

    response = await client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": COMBINED_PROMPT},
            {"role": "user", "content": content},
        ],
        response_format={
            "type": "json_schema",
            "json_schema": {
                "name": "compliance_report",
                "strict": True,
                "schema": REPORT_SCHEMA,
            },
        },
        temperature=0.1,
        max_tokens=1200,
    )

    raw = response.choices[0].message.content or "{}"
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return Report(
            video_id=video_id,
            summary="Failed to parse report.",
            overall_compliant=False,
            analyzed_at=datetime.now(timezone.utc).isoformat(),
            total_frames_analyzed=len(keyframes),
            video_duration=video_duration,
        )

    # Parse verdicts
    all_verdicts = []
    incidents = []
    for v in data.get("verdicts", []):
        verdict = Verdict(
            rule_type=v.get("rule_type", "unknown"),
            rule_description=v.get("rule_description", ""),
            compliant=v.get("compliant", True),
            severity=v.get("severity", "medium"),
            reason=v.get("reason", ""),
            timestamp=v.get("timestamp"),
        )
        all_verdicts.append(verdict)
        if not verdict.compliant:
            incidents.append(verdict)

    # Parse person summaries
    person_summaries = []
    for ps in data.get("person_summaries", []):
        person_summaries.append(PersonSummary(
            person_id=ps.get("person_id", "Unknown"),
            appearance=ps.get("appearance", ""),
            first_seen=ps.get("first_seen", 0.0),
            last_seen=ps.get("last_seen", 0.0),
            frames_seen=ps.get("frames_seen", 1),
            compliant=ps.get("compliant", True),
            violations=ps.get("violations", []),
            thumbnail_base64="",
        ))

    # Build frame observations (lightweight — just timestamps + images, no VLM descriptions)
    observations = [
        FrameObservation(
            timestamp=kf.timestamp,
            description="",
            trigger=kf.trigger,
            change_score=kf.change_score,
            image_base64=kf.image_base64,
        )
        for kf in keyframes
    ]

    return Report(
        video_id=video_id,
        summary=data.get("summary", "No summary."),
        overall_compliant=data.get("overall_compliant", True),
        incidents=incidents,
        all_verdicts=all_verdicts,
        recommendations=data.get("recommendations", []),
        frame_observations=observations,
        person_summaries=person_summaries,
        analyzed_at=datetime.now(timezone.utc).isoformat(),
        total_frames_analyzed=len(keyframes),
        video_duration=video_duration,
    )
