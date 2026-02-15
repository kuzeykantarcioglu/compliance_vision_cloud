"""VLM Service — sends keyframes to GPT-4o vision and gets scene descriptions.

This is the "eyes" of the system. For each keyframe, the VLM answers:
"What do you see?" with a focus on people, objects, actions, and environment.

Keyframes are batched (up to 5 per API call) to reduce latency and cost.
The policy context is included in the prompt so the VLM knows what to focus on.
"""

import asyncio
import json
from openai import AsyncOpenAI

from backend.core.config import OPENAI_API_KEY
from backend.models.schemas import KeyframeData, FrameObservation, Policy, ReferenceImage

client = AsyncOpenAI(api_key=OPENAI_API_KEY)


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
- **People**: count, approximate location in frame, clothing, badges/ID visible (color, type), PPE (helmets, vests, gloves, goggles), posture, actions
- **Objects**: bags, equipment, vehicles, signage, barriers, doors (open/closed)
- **Environment**: indoor/outdoor, lighting conditions, area type (industrial, office, retail, construction), any hazards visible
- **Actions/Events**: what is happening, movement patterns, interactions between people

Be specific and factual. Do not speculate or make assumptions beyond what is visible.
If something is unclear or partially obscured, say so.

Output your response as a JSON array with one object per image, in the same order as the images provided. Each object should have:
- "timestamp": the timestamp value provided for that image
- "description": your detailed observation (string)

Example output for 2 images:
[
  {"timestamp": 0.0, "description": "Indoor office space. 2 people visible. Person 1: standing near door, wearing blue lanyard with green badge visible. Person 2: seated at desk, no badge visible. Environment: well-lit, open floor plan."},
  {"timestamp": 5.0, "description": "Same space. Person 1 has exited frame. Person 2 still seated. A third person entering from left side wearing yellow hard hat and orange safety vest. Door in background is now open."}
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
        "Be conclusive — state YES or NO for each check, then explain. "
        "For people: compare facial features, hair, clothing, build. "
        "For badges: compare color, shape, logo, text. "
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

    # Add each surveillance keyframe
    for kf in batch:
        content.append({
            "type": "image_url",
            "image_url": {
                "url": f"data:image/jpeg;base64,{kf.image_base64}",
                "detail": "low",
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
        model="gpt-4o",
        messages=messages,
        max_tokens=1500,
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
            desc = parsed[i].get("description", str(parsed[i]))
        else:
            desc = "No observation returned for this frame."

        observations.append(FrameObservation(
            timestamp=kf.timestamp,
            description=desc,
            trigger=kf.trigger,
            change_score=kf.change_score,
            image_base64=kf.image_base64,
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

    # Run batches concurrently
    tasks = [_analyze_batch(batch, policy_context, effective) for batch in batches]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    # Flatten results, handle any failed batches gracefully
    all_observations = []
    for i, result in enumerate(results):
        if isinstance(result, Exception):
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

    return all_observations
