"""Policy Evaluation + Report Generation Service.

Single LLM call that takes VLM observations + policy rules and produces
a full structured compliance report. Uses GPT-4o-mini with structured
output (JSON schema) for reliable parsing.

Merging policy eval + report generation into one call saves ~30% latency
and one full API round-trip vs doing them separately.
"""

import json
from datetime import datetime, timezone

from openai import AsyncOpenAI

from backend.core.config import OPENAI_API_KEY
from backend.models.schemas import (
    FrameObservation,
    Policy,
    Report,
    TranscriptResult,
    Verdict,
)

client = AsyncOpenAI(api_key=OPENAI_API_KEY)

SYSTEM_PROMPT = """You are an expert compliance evaluator for a video surveillance monitoring system.

You will receive:
1. A set of visual observations from video frames (with timestamps)
2. A compliance policy with specific rules
3. Optionally, an audio transcript from the video (with timestamps)

Your job:
- Evaluate EACH policy rule against ALL observations AND the transcript (if provided)
- For each rule, determine: compliant or non-compliant
- Provide clear reasoning citing specific observations, transcript quotes, and timestamps
- Generate an executive summary
- Provide actionable recommendations

Be precise. Cite specific timestamps and observations in your reasoning.
When a transcript is provided, look for verbal cues: safety briefings, announcements, verbal confirmations, hostile language, profanity, or any spoken content relevant to the policy.
If the evidence is ambiguous, say so but still make a call (compliant/non-compliant).
If there is no evidence relevant to a rule, mark it as compliant with a note that no relevant activity was observed.

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
    },
    "required": ["summary", "overall_compliant", "verdicts", "recommendations"],
    "additionalProperties": False,
}


def _format_observations(observations: list[FrameObservation]) -> str:
    """Format VLM observations into a readable block for the LLM."""
    lines = []
    for obs in observations:
        trigger_tag = f"[{obs.trigger}]" if obs.trigger != "change" else ""
        lines.append(f"[t={obs.timestamp:.1f}s] {trigger_tag} {obs.description}")
    return "\n".join(lines)


def _format_policy(policy: Policy) -> str:
    """Format the policy into a readable block for the LLM."""
    lines = ["COMPLIANCE POLICY RULES:"]
    for i, rule in enumerate(policy.rules, 1):
        lines.append(f"  {i}. [{rule.severity.upper()}] ({rule.type}) {rule.description}")
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
) -> Report:
    """Evaluate observations against policy and generate a structured report.

    Single LLM call using GPT-4o-mini with structured output.

    Args:
        observations: VLM frame observations.
        policy: Compliance policy with rules.
        video_id: ID of the analyzed video.
        video_duration: Duration of the video in seconds.
        transcript: Optional Whisper transcript with timestamped segments.

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

    user_prompt += """

Evaluate each policy rule against these observations""" + (
        " and the audio transcript" if transcript_text else ""
    ) + ". Produce a compliance report."

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
        max_tokens=2000,
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

    return Report(
        video_id=video_id,
        summary=data.get("summary", "No summary generated."),
        overall_compliant=data.get("overall_compliant", True),
        incidents=incidents,
        all_verdicts=all_verdicts,
        recommendations=data.get("recommendations", []),
        frame_observations=observations,
        transcript=transcript,
        analyzed_at=datetime.now(timezone.utc).isoformat(),
        total_frames_analyzed=len(observations),
        video_duration=video_duration,
    )
