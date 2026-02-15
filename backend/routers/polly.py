"""Polly — AI Policy Creation Assistant.

Chat endpoint that takes a user message + the current policy state and returns
an updated policy with an explanation of what was changed.

Uses GPT-4o-mini with structured output to ensure the response always includes
a valid Policy object that can be directly applied in the UI.
"""

import json
import logging

from fastapi import APIRouter
from pydantic import BaseModel, Field
from openai import AsyncOpenAI

from backend.core.config import OPENAI_API_KEY
from backend.models.schemas import Policy

router = APIRouter(prefix="/polly", tags=["polly"])
logger = logging.getLogger(__name__)

client = AsyncOpenAI(api_key=OPENAI_API_KEY)

SYSTEM_PROMPT = """You are Polly, a friendly and expert compliance policy creation assistant.

You help users create, modify, and refine compliance monitoring policies through natural conversation. You understand:
- Visual compliance: PPE (helmets, vests, goggles), badges, access control, environment safety
- Audio compliance: verbal briefings, hostile language, required announcements
- Person/object matching: authorized personnel, approved badge designs, specific equipment

When the user describes what they want to monitor, you:
1. Create or modify policy rules with appropriate types and severity levels
2. Set the custom_prompt to guide the AI's focus
3. Enable include_audio if speech rules are needed
4. Explain what you changed and why

Rule types: "ppe", "badge", "presence", "action", "environment", "speech", "custom"
Severity levels: "low", "medium", "high", "critical"

Always return the COMPLETE updated policy — not just the changes. Include all existing rules that should be kept, plus any new/modified ones.

Be conversational and helpful. If the user's request is vague, ask clarifying questions but still provide a reasonable default policy. Suggest improvements they might not have thought of.

Keep responses concise — 2-4 sentences of explanation, then the policy."""

RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "message": {
            "type": "string",
            "description": "Polly's conversational response explaining what was created/changed. 2-4 sentences.",
        },
        "policy": {
            "type": "object",
            "properties": {
                "rules": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "type": {"type": "string"},
                            "description": {"type": "string"},
                            "severity": {"type": "string", "enum": ["low", "medium", "high", "critical"]},
                        },
                        "required": ["type", "description", "severity"],
                        "additionalProperties": False,
                    },
                },
                "custom_prompt": {"type": "string"},
                "include_audio": {"type": "boolean"},
            },
            "required": ["rules", "custom_prompt", "include_audio"],
            "additionalProperties": False,
        },
        "suggestions": {
            "type": "array",
            "items": {"type": "string"},
            "description": "2-3 follow-up suggestions the user might want to try next.",
        },
    },
    "required": ["message", "policy", "suggestions"],
    "additionalProperties": False,
}


class PollyRequest(BaseModel):
    message: str = Field(..., description="User's message to Polly")
    current_policy: Policy = Field(..., description="Current state of the policy in the UI")
    history: list[dict] = Field(
        default_factory=list,
        description="Chat history: [{role: 'user'|'assistant', content: str}]",
    )


class PollyResponse(BaseModel):
    message: str = Field(..., description="Polly's response")
    policy: Policy = Field(..., description="Updated policy to apply")
    suggestions: list[str] = Field(default_factory=list, description="Follow-up suggestions")


@router.post("/chat", response_model=PollyResponse)
async def polly_chat(req: PollyRequest):
    """Chat with Polly to create or modify compliance policies."""

    # Build conversation history
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]

    # Add chat history
    for h in req.history[-10:]:  # Keep last 10 messages for context
        messages.append({"role": h["role"], "content": h["content"]})

    # Current policy context
    current_rules = "\n".join(
        f"  - [{r.severity.upper()}] ({r.type}) {r.description}"
        for r in req.current_policy.rules
    ) or "  (no rules yet)"

    user_content = f"""Current policy state:
Rules:
{current_rules}
Custom prompt: "{req.current_policy.custom_prompt or '(empty)'}"
Audio analysis: {"enabled" if req.current_policy.include_audio else "disabled"}

User request: {req.message}"""

    messages.append({"role": "user", "content": user_content})

    response = await client.chat.completions.create(
        model="gpt-4o-mini",
        messages=messages,
        response_format={
            "type": "json_schema",
            "json_schema": {
                "name": "polly_response",
                "strict": True,
                "schema": RESPONSE_SCHEMA,
            },
        },
        temperature=0.7,
        max_tokens=1500,
    )

    raw = response.choices[0].message.content or "{}"

    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return PollyResponse(
            message="Sorry, I had trouble processing that. Could you try rephrasing?",
            policy=req.current_policy,
            suggestions=["Try describing what you want to monitor", "Ask me to add a specific rule"],
        )

    # Parse the policy, preserving reference_images and enabled_reference_ids from the current policy
    policy_data = data.get("policy", {})
    updated_policy = Policy(
        rules=[],
        custom_prompt=policy_data.get("custom_prompt", ""),
        include_audio=policy_data.get("include_audio", False),
        reference_images=req.current_policy.reference_images,  # Preserve references
        enabled_reference_ids=getattr(req.current_policy, "enabled_reference_ids", None) or [],
    )

    for r in policy_data.get("rules", []):
        from backend.models.schemas import PolicyRule
        updated_policy.rules.append(PolicyRule(
            type=r.get("type", "custom"),
            description=r.get("description", ""),
            severity=r.get("severity", "high"),
        ))

    return PollyResponse(
        message=data.get("message", "Policy updated."),
        policy=updated_policy,
        suggestions=data.get("suggestions", []),
    )
