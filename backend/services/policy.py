"""Policy Evaluation + Report Generation Service.

Single LLM call that takes VLM observations + policy rules and produces
a full structured compliance report. Uses GPT-4o-mini with structured
output (JSON schema) for reliable parsing.

Merging policy eval + report generation into one call saves ~30% latency
and one full API round-trip vs doing them separately.
"""

import json
import logging
import asyncio
from datetime import datetime, timezone

from backend.core.config import openai_client as client
from backend.services.api_utils import exponential_backoff_retry, track_usage, check_rate_limit, estimate_cost
from backend.services.compliance_state import compliance_tracker
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
- For "AT LEAST ONCE" / "AT LEAST N" rules: If prior context says ALREADY SATISFIED, mark COMPLIANT. Do NOT re-flag.
- For "ALWAYS" rules: Prior context is informational only. You MUST re-evaluate ALWAYS rules from scratch in every frame. A person who was compliant before may not be compliant now.

PER-PERSON EVALUATION:
- Evaluate each person individually against person-relevant rules.
- Produce a person_summaries array with one entry per tracked person.
- For frequency-based rules only: if a person was already marked compliant in prior context, keep them compliant.

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


def _apply_dual_mode_filtering(
    verdicts_data: list,
    policy: Policy,
    observations: list[FrameObservation]
) -> tuple[list[Verdict], list[Verdict]]:
    """Apply dual-mode filtering to verdicts.
    
    For checklist mode rules:
    - Check if compliance is still valid from previous verification
    - Update compliance state when rules are satisfied
    - Filter out spam violations for already-compliant items
    
    Returns: (all_verdicts, incidents)
    """
    all_verdicts = []
    incidents = []
    
    # Map rule descriptions to rule objects
    rule_map = {rule.description: rule for rule in policy.rules}
    
    # Get all person IDs from observations
    people_ids = set()
    for obs in observations:
        for person in obs.people:
            people_ids.add(person.person_id)
    if not people_ids:
        people_ids = {"unknown"}  # Default if no people identified
    
    for v in verdicts_data:
        rule_desc = v.get("rule_description", "")
        rule = rule_map.get(rule_desc)
        
        # Determine mode
        mode = rule.mode if rule else "incident"
        is_compliant = v.get("compliant", True)
        
        # For checklist mode, check and update state
        if mode == "checklist":
            # Check if anyone is still compliant from before
            anyone_still_compliant = False
            for person_id in people_ids:
                is_valid, state = compliance_tracker.check_compliance(person_id, rule)
                if is_valid:
                    anyone_still_compliant = True
                    # Override verdict to compliant
                    is_compliant = True
                    v["reason"] = f"Previously verified (still valid)"
                    break
            
            # Update state if newly compliant
            if is_compliant and not anyone_still_compliant:
                for person_id in people_ids:
                    compliance_tracker.update_compliance(person_id, rule, True)
        
        # Create verdict with mode info
        verdict = Verdict(
            rule_type=v.get("rule_type", "unknown"),
            rule_description=rule_desc,
            compliant=is_compliant,
            severity=v.get("severity", "medium"),
            reason=v.get("reason", ""),
            timestamp=v.get("timestamp"),
            mode=mode,
            checklist_status="compliant" if (mode == "checklist" and is_compliant) else None,
        )
        
        all_verdicts.append(verdict)

        # Only add to incidents if it's a real violation
        if not verdict.compliant:
            # Only incident-mode rules generate incidents.
            # Checklist-mode rules are tracked separately via checklist_fulfilled
            # and should never appear as incidents (even when pending/unfulfilled).
            if mode == "incident":
                incidents.append(verdict)
    
    return all_verdicts, incidents


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
        # Show mode instead of frequency
        mode = getattr(rule, "mode", "incident")
        mode_tag = "INCIDENT" if mode == "incident" else f"CHECKLIST"
        if mode == "checklist" and rule.validity_duration:
            mode_tag += f" ({rule.validity_duration}s validity)"
        lines.append(f"  {i}. [{rule.severity.upper()}] [{mode_tag}] ({rule.type}) {rule.description}")
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

    # Check rate limit
    if not check_rate_limit("policy_eval", max_per_minute=30, max_per_hour=500):
        logger.warning("⚠️ Policy evaluation rate limit approaching, adding delay...")
        await asyncio.sleep(2.0)

    # Wrap API call in retry logic
    async def make_api_call():
        return await client.chat.completions.create(
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

    response = await exponential_backoff_retry(
        make_api_call,
        max_retries=3,
        initial_delay=1.0,
        service_name="Policy Evaluation",
    )

    # Track usage
    if response.usage:
        cost = estimate_cost(
            "policy_eval",
            input_tokens=response.usage.prompt_tokens,
            output_tokens=response.usage.completion_tokens,
            model="gpt-4o-mini"
        )
        track_usage(
            "policy_eval",
            tokens=response.usage.total_tokens,
            cost=cost,
            metadata={"num_rules": len(policy.rules), "num_observations": len(observations)}
        )

    raw = response.choices[0].message.content or "{}"
    logger.info(f"Policy evaluation response received ({len(raw)} chars)")

    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        logger.error(f"Failed to parse policy evaluation JSON: {raw[:300]}")
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

    # Parse verdicts with dual-mode filtering
    all_verdicts, incidents = _apply_dual_mode_filtering(
        data.get("verdicts", []),
        policy,
        observations
    )

    # Compute checklist_fulfilled
    checklist_verdicts = [v for v in all_verdicts if v.mode == "checklist"]
    checklist_fulfilled = all(v.compliant for v in checklist_verdicts) if checklist_verdicts else None

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
        checklist_fulfilled=checklist_fulfilled,
        analyzed_at=datetime.now(timezone.utc).isoformat(),
        total_frames_analyzed=len(observations),
        video_duration=video_duration,
    )


# ---------------------------------------------------------------------------
# Combined single-call analysis (VLM + Policy in one shot) — for webcam chunks
# ---------------------------------------------------------------------------

COMBINED_PROMPT = """You are a compliance monitoring AI. Analyze frames against the policy.

FREQUENCY RULES:
- "ALWAYS" = must hold in EVERY frame. Always re-evaluate from scratch. Prior context for ALWAYS rules is informational only — judge this frame independently.
- "AT LEAST ONCE" = satisfied if seen in any frame. If prior context says already satisfied, mark COMPLIANT.

Use reference labels for known people, "Person_A" etc for unknown.
Be VERY brief. 1 short sentence per field max."""

# Leaner schema for webcam chunks — fewer output tokens = faster response
COMBINED_REPORT_SCHEMA = {
    "type": "object",
    "properties": {
        "summary": {
            "type": "string",
            "description": "1 sentence: # violations and status.",
        },
        "overall_compliant": {"type": "boolean"},
        "verdicts": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "rule_description": {"type": "string"},
                    "compliant": {"type": "boolean"},
                    "severity": {"type": "string", "enum": ["low", "medium", "high", "critical"]},
                    "reason": {"type": "string", "description": "1 sentence max."},
                    "timestamp": {"type": ["number", "null"]},
                },
                "required": ["rule_description", "compliant", "severity", "reason", "timestamp"],
                "additionalProperties": False,
            },
        },
        "person_summaries": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "person_id": {"type": "string"},
                    "appearance": {"type": "string"},
                    "first_seen": {"type": "number"},
                    "last_seen": {"type": "number"},
                    "frames_seen": {"type": "integer"},
                    "compliant": {"type": "boolean"},
                    "violations": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["person_id", "appearance", "first_seen", "last_seen", "frames_seen", "compliant", "violations"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["summary", "overall_compliant", "verdicts", "person_summaries"],
    "additionalProperties": False,
}


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
    # detail:"low" = fixed 85 tokens/image (vs ~1100 for "auto") — much faster
    for kf in keyframes:
        content.append({"type": "text", "text": f"[Frame at t={kf.timestamp:.1f}s]"})
        content.append({
            "type": "image_url",
            "image_url": {"url": f"data:image/jpeg;base64,{kf.image_base64}", "detail": "low"},
        })

    logger.info(f"Combined analysis: {len(keyframes)} frames, {len(policy.rules)} rules")

    # Check rate limit
    if not check_rate_limit("combined_analysis", max_per_minute=60, max_per_hour=1000):
        logger.warning("⚠️ Combined analysis rate limit approaching, adding delay...")
        await asyncio.sleep(1.5)

    # Wrap API call in retry logic
    async def make_api_call():
        return await client.chat.completions.create(
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
                    "schema": COMBINED_REPORT_SCHEMA,
                },
            },
            temperature=0.0,
            max_tokens=600,
        )

    response = await exponential_backoff_retry(
        make_api_call,
        max_retries=3,
        initial_delay=0.5,  # Faster retry for webcam
        service_name="Combined Analysis",
    )

    # Track usage
    if response.usage:
        cost = estimate_cost(
            "combined_analysis",
            input_tokens=response.usage.prompt_tokens,
            output_tokens=response.usage.completion_tokens,
            model="gpt-4o-mini"
        )
        track_usage(
            "combined_analysis",
            tokens=response.usage.total_tokens,
            cost=cost,
            metadata={"num_frames": len(keyframes)}
        )

    raw = response.choices[0].message.content or "{}"
    logger.info(f"Combined analysis response received ({len(raw)} chars)")
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        logger.error(f"Failed to parse combined analysis JSON: {raw[:300]}")
        return Report(
            video_id=video_id,
            summary="Failed to parse report.",
            overall_compliant=False,
            analyzed_at=datetime.now(timezone.utc).isoformat(),
            total_frames_analyzed=len(keyframes),
            video_duration=video_duration,
        )

    # Parse frame observations if present
    observations = []
    for obs in data.get("frame_observations", []):
        observations.append(FrameObservation(
            timestamp=obs.get("timestamp", 0.0),
            description=obs.get("description", ""),
            trigger=obs.get("trigger", "monitoring"),
            change_score=obs.get("change_score", 1.0),
            image_base64=keyframes[0].image_base64 if keyframes else "",
            people=[]
        ))

    # Parse verdicts with dual-mode filtering
    all_verdicts, incidents = _apply_dual_mode_filtering(
        data.get("verdicts", []),
        policy,
        observations
    )

    # Compute checklist_fulfilled
    checklist_verdicts = [v for v in all_verdicts if v.mode == "checklist"]
    checklist_fulfilled = all(v.compliant for v in checklist_verdicts) if checklist_verdicts else None

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

    # If we didn't get observations from the response, build them from keyframes
    if not observations:
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
        checklist_fulfilled=checklist_fulfilled,
        analyzed_at=datetime.now(timezone.utc).isoformat(),
        total_frames_analyzed=len(keyframes),
        video_duration=video_duration,
    )
