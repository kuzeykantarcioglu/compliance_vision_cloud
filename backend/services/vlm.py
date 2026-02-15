"""VLM Service — sends keyframes to GPT-4o vision and gets scene descriptions.

This is the "eyes" of the system. For each keyframe, the VLM answers:
"What do you see?" with a focus on people, objects, actions, and environment.

Keyframes are batched (up to 5 per API call) to reduce latency and cost.
The policy context is included in the prompt so the VLM knows what to focus on.
"""

import asyncio
import json
import logging

from backend.core.config import openai_client as client
from backend.models.schemas import KeyframeData, FrameObservation, PersonDetail, Policy, ReferenceImage

logger = logging.getLogger(__name__)


def _effective_reference_images(policy: Policy) -> list[ReferenceImage]:
    """Only references whose id is in enabled_reference_ids are sent to the VLM."""
    enabled = getattr(policy, "enabled_reference_ids", None) or []
    if not enabled:
        return []
    return [r for r in policy.reference_images if getattr(r, "id", None) and r.id in enabled]

# Max keyframes per single API call (GPT-4o supports multi-image)
BATCH_SIZE = 5

SYSTEM_PROMPT = """You are a visual surveillance analyst for a compliance monitoring system.

For each image provided, describe what you see concisely and factually. Focus on:
- **People**: count, location, clothing, badges/ID visible, PPE, posture, actions
- **Objects**: equipment, signage, barriers, doors
- **Environment**: indoor/outdoor, area type, hazards
- **Actions**: what is happening, movement patterns

PERSON IDENTIFICATION:
1. If REFERENCE IMAGES of people are provided, compare each visible person against them.
   - If a person matches a reference image, use the reference label as their person_id (e.g., "Kuzey" not "Person_A").
   - Compare face, hair, build, clothing, glasses, and other features.
   - Be confident: if there's a strong match, use the reference name.
2. For people who do NOT match any reference, assign generic IDs: "Person_A", "Person_B", etc.
3. Use the SAME identifier for the same person across multiple frames.

Be concise and factual. If something is unclear, note it briefly.

Output JSON array, one object per image:
- "timestamp": the timestamp value
- "description": concise observation (1-2 sentences)
- "people": array of people visible:
  - "person_id": reference label if matched, else "Person_A" etc.
  - "appearance": brief description (clothing, build, hair)
  - "details": compliance-relevant details (badges, PPE, actions)

Example:
[
  {"timestamp": 0.0, "description": "Indoor office. 2 people visible.", "people": [{"person_id": "Kuzey", "appearance": "curly hair, glasses, green shirt", "details": "standing near door, wearing green badge, waving"}, {"person_id": "Person_B", "appearance": "woman, red sweater", "details": "seated, no badge visible"}]}
]"""


def _effective_policy(policy: Policy) -> Policy:
    """Policy with only enabled reference images (for VLM)."""
    refs = _effective_reference_images(policy)
    if refs == list(policy.reference_images):
        return policy
    return policy.model_copy(update={"reference_images": refs})


def _build_policy_context(policy: Policy) -> str:
    """Format the policy into a string the VLM can use to focus its observations."""
    if not policy.rules and not policy.custom_prompt and not policy.reference_images:
        return ""

    parts = ["Pay special attention to the following compliance requirements:"]
    for rule in policy.rules:
        parts.append(f"- [{rule.severity.upper()}] {rule.description}")
    if policy.custom_prompt:
        parts.append(f"\nAdditional context: {policy.custom_prompt}")

    return "\n".join(parts)


def _build_reference_context(policy: Policy) -> str:
    """Build structured per-reference instructions for the VLM."""
    if not policy.reference_images:
        return ""

    parts = ["\nVISUAL REFERENCE IMAGES are provided before the surveillance frames."]
    parts.append("For EACH reference image, answer the specific checks listed below.\n")

    for i, ref in enumerate(policy.reference_images):
        mode_label = "AUTHORIZED" if ref.match_mode == "must_match" else "UNAUTHORIZED"
        category = ref.category.upper() if ref.category else "REFERENCE"
        parts.append(f"  REFERENCE {i + 1} [{category}] [{mode_label}]: \"{ref.label}\"")

        if ref.checks:
            parts.append(f"    Checks for this reference:")
            for ci, check in enumerate(ref.checks):
                if check.strip():
                    parts.append(f"      {ci + 1}. {check}")
        else:
            # Fallback instructions if no checks specified
            if ref.match_mode == "must_match":
                parts.append(f"    Check: Is this {ref.category or 'item'} present/visible in the frame?")
            else:
                parts.append(f"    Check: Is this {ref.category or 'item'} present? It should NOT be.")
        parts.append("")

    parts.append(
        "For each reference, answer each check explicitly in your observation. "
        "Be conclusive — state YES or NO for each check, then explain.\n"
        "For PEOPLE references: compare face, hair, build, clothing, glasses. "
        "If a person matches a people reference, use the reference LABEL as their person_id in the 'people' array "
        "(e.g., if reference is labeled 'Kuzey' and someone matches, use person_id='Kuzey').\n"
        "For badges: compare color, shape, logo, text.\n"
        "For objects: compare shape, size, color, markings."
    )
    return "\n".join(parts)


def _build_batch_messages(
    batch: list[KeyframeData],
    policy_context: str,
    policy: Policy,
) -> list[dict]:
    """Build the OpenAI chat messages for a batch of keyframes."""
    content = []

    # Text intro with timestamps
    ts_list = ", ".join(f"{kf.timestamp}s" for kf in batch)
    text = f"Analyze the following {len(batch)} frame(s) from a surveillance video (timestamps: {ts_list})."
    if policy_context:
        text += f"\n\n{policy_context}"

    # Add reference image context
    ref_context = _build_reference_context(policy)
    if ref_context:
        text += f"\n{ref_context}"

    content.append({"type": "text", "text": text})

    # Add reference images FIRST (before surveillance frames) so the VLM sees them as context
    for i, ref in enumerate(policy.reference_images):
        content.append({"type": "text", "text": f"[REFERENCE {i + 1}: {ref.label}]"})
        # Detect format from base64 header or default to jpeg
        mime = "image/png" if ref.image_base64[:4] == "iVBO" else "image/jpeg"
        content.append({
            "type": "image_url",
            "image_url": {
                "url": f"data:{mime};base64,{ref.image_base64}",
                "detail": "low",
            },
        })

    # Separator if we have references
    if policy.reference_images:
        content.append({"type": "text", "text": "[SURVEILLANCE FRAMES BELOW]"})

    # Add each surveillance keyframe — detail:auto for action recognition
    for kf in batch:
        content.append({
            "type": "image_url",
            "image_url": {
                "url": f"data:image/jpeg;base64,{kf.image_base64}",
                "detail": "auto",
            },
        })

    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": content},
    ]


async def _analyze_batch(
    batch: list[KeyframeData],
    policy_context: str,
    policy: Policy,
) -> list[FrameObservation]:
    """Send a batch of keyframes to GPT-4o and parse observations."""
    messages = _build_batch_messages(batch, policy_context, policy)

    response = await client.chat.completions.create(
        model="gpt-4o-mini",
        messages=messages,
        max_tokens=1000,
        temperature=0.1,  # Low temp for factual descriptions
    )

    raw_text = response.choices[0].message.content or "[]"

    # Parse JSON array from response — handle markdown code fences
    raw_text = raw_text.strip()
    if raw_text.startswith("```"):
        # Strip ```json ... ``` wrapper
        lines = raw_text.split("\n")
        raw_text = "\n".join(lines[1:-1])

    try:
        parsed = json.loads(raw_text)
    except json.JSONDecodeError:
        # Fallback: treat entire response as a single observation for all frames
        parsed = [
            {"timestamp": kf.timestamp, "description": raw_text}
            for kf in batch
        ]

    # Map parsed results back to FrameObservation, matching by order
    observations = []
    for i, kf in enumerate(batch):
        if i < len(parsed):
            item = parsed[i] if isinstance(parsed[i], dict) else {}
            desc = item.get("description", str(parsed[i]))
            # Parse people array from VLM response
            raw_people = item.get("people", [])
            people = []
            for p in raw_people:
                if isinstance(p, dict) and "person_id" in p:
                    people.append(PersonDetail(
                        person_id=p.get("person_id", "Unknown"),
                        appearance=p.get("appearance", ""),
                        details=p.get("details", ""),
                    ))
        else:
            desc = "No observation returned for this frame."
            people = []

        observations.append(FrameObservation(
            timestamp=kf.timestamp,
            description=desc,
            trigger=kf.trigger,
            change_score=kf.change_score,
            image_base64=kf.image_base64,
            people=people,
        ))

    return observations


async def analyze_frames(
    keyframes: list[KeyframeData],
    policy: Policy,
) -> list[FrameObservation]:
    """Analyze all keyframes using GPT-4o vision.

    Keyframes are batched (up to BATCH_SIZE per call) and sent concurrently.
    Only references in policy.enabled_reference_ids are sent to the VLM.

    Args:
        keyframes: List of keyframes with base64 images from change detection.
        policy: The compliance policy — used to focus VLM attention.

    Returns:
        List of FrameObservation with text descriptions per keyframe.
    """
    if not keyframes:
        return []

    effective = _effective_policy(policy)
    policy_context = _build_policy_context(effective)

    # Reduce batch size when reference images are present (each ref = 1 extra image in the call)
    effective_batch = max(1, BATCH_SIZE - len(effective.reference_images))

    # Split into batches
    batches = [
        keyframes[i : i + effective_batch]
        for i in range(0, len(keyframes), effective_batch)
    ]

    logger.info(f"VLM analysis: {len(keyframes)} keyframes in {len(batches)} batch(es) (batch_size={effective_batch}, refs={len(effective.reference_images)})")

    # Run batches concurrently
    tasks = [_analyze_batch(batch, policy_context, effective) for batch in batches]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    # Flatten results, handle any failed batches gracefully
    all_observations = []
    for i, result in enumerate(results):
        if isinstance(result, Exception):
            logger.error(f"VLM batch {i+1}/{len(batches)} FAILED: {result}", exc_info=result)
            # If a batch failed, create placeholder observations
            for kf in batches[i]:
                all_observations.append(FrameObservation(
                    timestamp=kf.timestamp,
                    description=f"[VLM ERROR] {str(result)}",
                    trigger=kf.trigger,
                    change_score=kf.change_score,
                    image_base64=kf.image_base64,
                ))
        else:
            all_observations.extend(result)

    logger.info(f"VLM analysis complete: {len(all_observations)} observations")
    return all_observations
