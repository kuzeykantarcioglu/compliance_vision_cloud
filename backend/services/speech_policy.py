"""Speech Policy Evaluation Service.

Dedicated pipeline for speech/audio compliance rules.
Takes a Whisper transcript + speech-type policy rules and evaluates them
using GPT-4o-mini. No images involved — pure text analysis.

This runs SEPARATELY from the visual policy evaluator, in parallel.
Results are merged into the final report by the router.
"""

import json
import logging

from backend.core.config import openai_client as client
from backend.models.schemas import (
    PolicyRule,
    TranscriptResult,
    Verdict,
)

logger = logging.getLogger(__name__)

SPEECH_SYSTEM_PROMPT = """You are an expert audio/speech compliance evaluator.

You will receive:
1. A transcript of audio from a video, with timestamped segments
2. A set of speech compliance rules to evaluate

Your job:
- Evaluate EACH rule against the transcript
- For each rule, determine: compliant or non-compliant
- Count occurrences of specific phrases when required
- Quote the exact transcript segments that support your reasoning
- Cite timestamps from the transcript

Be precise. If a rule requires a phrase to be said N times, count the EXACT number of occurrences.
If the transcript is empty or too short to evaluate, mark rules as non-compliant with a note.

Severity levels: "low", "medium", "high", "critical"
"""

SPEECH_VERDICTS_SCHEMA = {
    "type": "object",
    "properties": {
        "verdicts": {
            "type": "array",
            "description": "One verdict per speech rule.",
            "items": {
                "type": "object",
                "properties": {
                    "rule_type": {"type": "string"},
                    "rule_description": {"type": "string"},
                    "compliant": {"type": "boolean"},
                    "severity": {"type": "string", "enum": ["low", "medium", "high", "critical"]},
                    "reason": {
                        "type": "string",
                        "description": "Reasoning with exact quotes and counts from the transcript.",
                    },
                    "timestamp": {
                        "type": ["number", "null"],
                        "description": "Timestamp of first relevant occurrence, or null.",
                    },
                },
                "required": ["rule_type", "rule_description", "compliant", "severity", "reason", "timestamp"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["verdicts"],
    "additionalProperties": False,
}


def _format_transcript(transcript: TranscriptResult) -> str:
    """Format transcript for the LLM."""
    lines = [f"AUDIO TRANSCRIPT (language: {transcript.language}, duration: {transcript.duration:.1f}s):"]
    if transcript.segments:
        for seg in transcript.segments:
            lines.append(f"  [{seg.start:.1f}s - {seg.end:.1f}s] {seg.text.strip()}")
    else:
        lines.append(f"  {transcript.full_text}")
    return "\n".join(lines)


def _format_speech_rules(rules: list[PolicyRule], custom_prompt: str) -> str:
    """Format speech rules for the LLM."""
    lines = ["SPEECH COMPLIANCE RULES:"]
    for i, rule in enumerate(rules, 1):
        lines.append(f"  {i}. [{rule.severity.upper()}] {rule.description}")
    if custom_prompt:
        lines.append(f"\nADDITIONAL CONTEXT: {custom_prompt}")
    return "\n".join(lines)


async def evaluate_speech(
    transcript: TranscriptResult,
    speech_rules: list[PolicyRule],
    custom_prompt: str = "",
    accumulated_transcript: str = "",
) -> list[Verdict]:
    """Evaluate speech rules against a transcript.

    Args:
        transcript: Whisper transcript with timestamped segments (current chunk).
        speech_rules: Only the rules with type="speech".
        custom_prompt: Additional context from the policy.
        accumulated_transcript: Full transcript text accumulated from all prior chunks.

    Returns:
        List of Verdict objects for each speech rule.
    """
    if not speech_rules:
        return []

    logger.info(f"Evaluating {len(speech_rules)} speech rules against transcript")

    # Build the full transcript: accumulated history + current chunk
    current_text = transcript.full_text if transcript else ""
    full_text = (accumulated_transcript + " " + current_text).strip() if accumulated_transcript else current_text

    if not full_text:
        logger.warning("No audio transcript available — marking all speech rules as non-compliant")
        return [
            Verdict(
                rule_type="speech",
                rule_description=rule.description,
                compliant=False,
                severity=rule.severity,
                reason="No audio transcript available. Cannot evaluate speech compliance.",
                timestamp=None,
            )
            for rule in speech_rules
        ]

    # Format combined transcript for the LLM
    transcript_lines = ["FULL ACCUMULATED TRANSCRIPT (across all monitoring chunks):"]
    if accumulated_transcript:
        transcript_lines.append(f"  [Prior chunks] {accumulated_transcript}")
    if transcript and transcript.segments:
        transcript_lines.append("  [Current chunk]:")
        for seg in transcript.segments:
            transcript_lines.append(f"    [{seg.start:.1f}s - {seg.end:.1f}s] {seg.text.strip()}")
    elif current_text:
        transcript_lines.append(f"  [Current chunk] {current_text}")
    transcript_text = "\n".join(transcript_lines)

    rules_text = _format_speech_rules(speech_rules, custom_prompt)

    user_prompt = f"""{rules_text}

{transcript_text}

Evaluate each speech rule against the FULL ACCUMULATED transcript (all chunks combined). Be precise — count exact phrase occurrences across the entire session, quote relevant segments."""

    response = await client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": SPEECH_SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
        response_format={
            "type": "json_schema",
            "json_schema": {
                "name": "speech_verdicts",
                "strict": True,
                "schema": SPEECH_VERDICTS_SCHEMA,
            },
        },
        temperature=0.1,
        max_tokens=1500,
    )

    raw = response.choices[0].message.content or "{}"

    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        logger.error(f"Failed to parse speech evaluation JSON from LLM: {raw[:200]}")
        return [
            Verdict(
                rule_type="speech",
                rule_description=rule.description,
                compliant=False,
                severity=rule.severity,
                reason="Failed to parse speech evaluation from LLM.",
                timestamp=None,
            )
            for rule in speech_rules
        ]

    # Map rule descriptions to rule objects to carry over mode
    rule_map = {rule.description: rule for rule in speech_rules}

    verdicts = []
    for v in data.get("verdicts", []):
        rule_desc = v.get("rule_description", "")
        rule = rule_map.get(rule_desc)
        mode = rule.mode if rule else "incident"
        logger.info(f"  Speech rule '{rule_desc[:50]}' [{mode}]: {'COMPLIANT' if v.get('compliant') else 'NON-COMPLIANT'}")
        verdicts.append(Verdict(
            rule_type=v.get("rule_type", "speech"),
            rule_description=rule_desc,
            compliant=v.get("compliant", False),
            severity=v.get("severity", "medium"),
            reason=v.get("reason", ""),
            timestamp=v.get("timestamp"),
            mode=mode,
            checklist_status="compliant" if (mode == "checklist" and v.get("compliant")) else None,
        ))

    return verdicts
