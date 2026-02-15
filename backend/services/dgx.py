"""DGX Spark Service — sends frames to NVIDIA DGX Spark (Cosmos + Nemotron pipeline).

Alternative to the OpenAI VLM pipeline. Sends webcam frames to a DGX Spark proxy,
which runs them through Cosmos (vision) → Nemotron (compliance) and returns a
structured compliance report.

The DGX proxy expects an OpenAI-compatible message format with video_url type.
Even for single frames, we wrap them as video_url to match the Cosmos input format.
"""

import asyncio
import base64
import json
import logging
import tempfile
import uuid
from datetime import datetime, timezone

import cv2
import numpy as np
import requests as sync_requests

from backend.core.config import DGX_PROXY_URL, DGX_MODEL_ID
from backend.models.schemas import (
    PersonSummary,
    Policy,
    Report,
    Verdict,
)

logger = logging.getLogger(__name__)

# Use synchronous requests library (httpx.AsyncClient has Windows async socket issues).
# Calls are run in a thread pool via asyncio.to_thread to avoid blocking the event loop.


def _build_dgx_prompt(policy: Policy) -> str:
    """Build a compliance prompt from the user's policy rules for DGX."""
    parts = [
        "You are a security camera AI compliance monitor.",
        "",
        "COMPLIANCE RULES TO CHECK:",
    ]

    for i, rule in enumerate(policy.rules, 1):
        parts.append(f"  {i}. [{rule.severity.upper()}] ({rule.type}) {rule.description}")

    if policy.custom_prompt:
        parts.append(f"\nADDITIONAL CONTEXT: {policy.custom_prompt}")

    parts.append("""
JOB: Analyze the image/video and evaluate compliance against ALL rules above.

RESPOND IN THIS EXACT JSON FORMAT:
{
  "overall_status": "compliant" or "non_compliant",
  "summary": "Brief 1-2 sentence summary of findings",
  "people_count": <number>,
  "people": [
    {
      "person_id": "Person 1",
      "appearance": "brief appearance description",
      "compliant": true or false,
      "violations": ["list of violated rule descriptions"]
    }
  ],
  "violations": [
    {
      "subject": "Person 1 or object description",
      "rule": "Which rule was violated",
      "description": "Brief explanation"
    }
  ],
  "verdicts": [
    {
      "rule_description": "The rule text",
      "compliant": true or false,
      "severity": "low/medium/high/critical",
      "reason": "Why compliant or not"
    }
  ]
}

RULES:
- Evaluate EVERY rule listed above
- If no people are visible, return people_count: 0 and mark people-related rules as "no people visible"
- Return ONLY the JSON, no other text
""")

    return "\n".join(parts)


def _frames_to_mp4_base64(frame_b64_list: list[str], fps: int = 4) -> str:
    """Convert a list of base64-encoded JPEG frames into an mp4 video (base64).

    Replicates exactly what security.py does:
      1. Decode each JPEG → OpenCV frame
      2. Write all frames to a temp mp4 file using cv2.VideoWriter
      3. Read back the mp4 and base64-encode it

    This is the format the DGX Cosmos proxy expects.
    """
    import os as _os

    if not frame_b64_list:
        raise ValueError("No frames provided for mp4 conversion")

    # Decode all JPEGs → numpy arrays
    cv_frames = []
    for i, b64 in enumerate(frame_b64_list):
        jpeg_bytes = base64.b64decode(b64)
        arr = np.frombuffer(jpeg_bytes, dtype=np.uint8)
        frame = cv2.imdecode(arr, cv2.IMREAD_COLOR)
        if frame is not None:
            cv_frames.append(frame)
        else:
            logger.warning(f"Frame {i} failed to decode, skipping")

    if not cv_frames:
        raise ValueError("All frames failed to decode")

    h, w = cv_frames[0].shape[:2]

    # Create temp mp4 file — use mkstemp to avoid Windows file-locking issues
    fd, tmp_path = tempfile.mkstemp(suffix=".mp4")
    _os.close(fd)  # close the fd so cv2 can write to it

    try:
        writer = cv2.VideoWriter(tmp_path, cv2.VideoWriter_fourcc(*"mp4v"), fps, (w, h))
        for f in cv_frames:
            writer.write(f)
        writer.release()

        with open(tmp_path, "rb") as f:
            video_b64 = base64.b64encode(f.read()).decode()
    finally:
        try:
            _os.unlink(tmp_path)
        except OSError:
            pass

    logger.info(
        f"🎞️  Created mp4 from {len(cv_frames)} frames ({w}x{h} @ {fps}fps) "
        f"→ {len(video_b64)} chars base64"
    )
    return video_b64


def _build_dgx_request(frames_b64: list[str], policy: Policy) -> dict:
    """Build the DGX proxy request payload from multiple JPEG frames.

    Converts the JPEG frames into an mp4 video clip (exactly like security.py),
    then wraps it as a data URI inside the OpenAI-compatible message format.
    Uses 'video_url' type with 'video/mp4' MIME to match what the DGX
    Cosmos proxy expects.
    """
    prompt = _build_dgx_prompt(policy)

    # Convert JPEG frames → mp4 video (exactly like security.py)
    video_b64 = _frames_to_mp4_base64(frames_b64, fps=4)

    return {
        "model": DGX_MODEL_ID,
        "messages": [
            {
                "role": "user",
                "content": [
                    {
                        "type": "video_url",
                        "video_url": {
                            "url": f"data:video/mp4;base64,{video_b64}"
                        },
                    },
                    {
                        "type": "text",
                        "text": prompt,
                    },
                ],
            }
        ],
        "max_tokens": 2048,
        "temperature": 0.6,
    }


def _parse_dgx_response(data: dict, policy: Policy, video_id: str) -> Report:
    """Parse DGX proxy response into our standard Report format.

    The DGX proxy returns a compliance report from Nemotron with:
      - overall_status: "compliant" / "non_compliant"
      - violations: [{subject, rule, description}]
      - Possibly: summary, people, verdicts
    """
    # Handle error responses
    if "error" in data:
        error_msg = data["error"]
        if isinstance(error_msg, dict):
            error_msg = error_msg.get("message", str(error_msg))
        return Report(
            video_id=video_id,
            summary=f"DGX Error: {error_msg}",
            overall_compliant=False,
            analyzed_at=datetime.now(timezone.utc).isoformat(),
            total_frames_analyzed=1,
            video_duration=0.0,
        )

    # The response might be in OpenAI chat format or direct JSON
    # Try to extract from chat completion format first
    raw_content = None
    if "choices" in data:
        try:
            raw_content = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError):
            pass

    if raw_content:
        # Parse the JSON from the model's text response
        raw_content = raw_content.strip()
        if raw_content.startswith("```"):
            lines = raw_content.split("\n")
            raw_content = "\n".join(lines[1:-1])
        try:
            data = json.loads(raw_content)
        except json.JSONDecodeError:
            logger.warning(f"DGX response not valid JSON, using raw text: {raw_content[:200]}")
            return Report(
                video_id=video_id,
                summary=raw_content[:500],
                overall_compliant=False,
                analyzed_at=datetime.now(timezone.utc).isoformat(),
                total_frames_analyzed=1,
                video_duration=0.0,
            )

    # Parse the compliance data
    overall_status = data.get("overall_status", "unknown").lower()
    overall_compliant = overall_status in ("compliant", "clear", "ok")
    summary = data.get("summary", f"DGX Status: {overall_status.upper()}")

    # Parse violations into Verdict objects
    violations_raw = data.get("violations", [])
    verdicts_raw = data.get("verdicts", [])

    all_verdicts = []
    incidents = []

    # First, try structured verdicts from the response
    if verdicts_raw:
        for v in verdicts_raw:
            verdict = Verdict(
                rule_type="dgx",
                rule_description=v.get("rule_description", v.get("rule", "Unknown rule")),
                compliant=v.get("compliant", True),
                severity=v.get("severity", "medium"),
                reason=v.get("reason", v.get("description", "")),
                timestamp=0.0,
            )
            all_verdicts.append(verdict)
            if not verdict.compliant:
                incidents.append(verdict)
    else:
        # Build verdicts from policy rules + violations list
        violation_rules = {v.get("rule", ""): v for v in violations_raw}

        for rule in policy.rules:
            matching_violation = None
            for vr in violations_raw:
                # fuzzy match: check if rule description appears in violation
                if (rule.description.lower() in vr.get("rule", "").lower()
                        or vr.get("rule", "").lower() in rule.description.lower()):
                    matching_violation = vr
                    break

            if matching_violation:
                verdict = Verdict(
                    rule_type=rule.type,
                    rule_description=rule.description,
                    compliant=False,
                    severity=rule.severity,
                    reason=f"{matching_violation.get('subject', 'Unknown')}: {matching_violation.get('description', '')}",
                    timestamp=0.0,
                )
                incidents.append(verdict)
            else:
                verdict = Verdict(
                    rule_type=rule.type,
                    rule_description=rule.description,
                    compliant=True,
                    severity=rule.severity,
                    reason="No violation detected by DGX analysis.",
                    timestamp=None,
                )
            all_verdicts.append(verdict)

        # Add any violations that don't match a rule
        for vr in violations_raw:
            already_mapped = any(
                not v.compliant and vr.get("rule", "").lower() in v.reason.lower()
                for v in all_verdicts
            )
            if not already_mapped:
                verdict = Verdict(
                    rule_type="dgx",
                    rule_description=vr.get("rule", "DGX Detected Violation"),
                    compliant=False,
                    severity="high",
                    reason=f"{vr.get('subject', 'Unknown')}: {vr.get('description', '')}",
                    timestamp=0.0,
                )
                all_verdicts.append(verdict)
                incidents.append(verdict)

    # Parse person summaries
    person_summaries = []
    for p in data.get("people", []):
        if isinstance(p, dict):
            person_summaries.append(PersonSummary(
                person_id=p.get("person_id", p.get("person", "Unknown")),
                appearance=p.get("appearance", p.get("description", "")),
                first_seen=0.0,
                last_seen=0.0,
                frames_seen=1,
                compliant=p.get("compliant", p.get("badge_visible", True)),
                violations=p.get("violations", []),
                thumbnail_base64="",
            ))

    # Build recommendations from violations
    recommendations = []
    for v in incidents[:5]:
        recommendations.append(f"Address: {v.reason}")
    if not recommendations:
        recommendations.append("All rules compliant per DGX analysis.")

    return Report(
        video_id=video_id,
        summary=summary,
        overall_compliant=overall_compliant,
        incidents=incidents,
        all_verdicts=all_verdicts,
        recommendations=recommendations,
        frame_observations=[],
        person_summaries=person_summaries,
        analyzed_at=datetime.now(timezone.utc).isoformat(),
        total_frames_analyzed=1,
        video_duration=0.0,
    )


async def analyze_frame_dgx(
    image_base64: str,
    policy: Policy,
    video_id: str | None = None,
    frames: list[str] | None = None,
) -> Report:
    """Send frames to DGX Spark proxy for compliance analysis.

    Replicates the security.py approach: multiple JPEG frames → mp4 video → DGX.

    Args:
        image_base64: Base64-encoded JPEG image (fallback if frames not provided).
        policy: Compliance policy with rules to evaluate.
        video_id: Optional ID for the report; auto-generated if not provided.
        frames: List of base64-encoded JPEG frames (preferred for DGX).
                 If provided, these are stitched into an mp4 video.
                 If not provided, falls back to single image_base64 (repeated 4x).

    Returns:
        Report in the same format as the OpenAI pipeline.
    """
    if not video_id:
        video_id = f"dgx-frame-{uuid.uuid4().hex[:8]}"

    # Use frames batch if provided, otherwise fall back to single frame repeated
    if frames and len(frames) > 0:
        frames_to_send = frames
        logger.info(f"🟢 DGX: using {len(frames)} buffered frames")
    else:
        # Fallback: repeat single frame 4x (like a 1-second clip)
        frames_to_send = [image_base64] * 4
        logger.info(f"🟢 DGX: single frame fallback (repeated 4x)")

    payload = _build_dgx_request(frames_to_send, policy)

    # ── Log outgoing request ──────────────────────────────────────────
    logger.info(
        f"➡️  DGX REQUEST  url={DGX_PROXY_URL}  model={DGX_MODEL_ID}\n"
        f"    frames={len(frames_to_send)}\n"
        f"    prompt (first 300 chars): {_build_dgx_prompt(policy)[:300]}"
    )
    # Log the full payload structure (with video data truncated)
    payload_log = json.loads(json.dumps(payload))  # deep copy
    try:
        for msg in payload_log.get("messages", []):
            for part in msg.get("content", []):
                if part.get("type") == "video_url":
                    url = part["video_url"]["url"]
                    part["video_url"]["url"] = url[:60] + f"...[{len(url)} chars total]"
    except Exception:
        pass
    logger.info(f"➡️  DGX PAYLOAD: {json.dumps(payload_log, indent=2)}")

    # ── Send request synchronously in a thread pool ───────────────────
    # (httpx.AsyncClient has Windows async socket issues; requests works reliably)
    def _send_sync():
        return sync_requests.post(
            DGX_PROXY_URL,
            json=payload,
            timeout=300,  # 5 min — Cosmos + Nemotron pipeline can take a while
        )

    try:
        response = await asyncio.to_thread(_send_sync)

        # ── Log raw HTTP response ─────────────────────────────────────
        logger.info(
            f"⬅️  DGX HTTP RESPONSE  status={response.status_code}  "
            f"content_length={response.headers.get('content-length', '?')}  "
            f"content_type={response.headers.get('content-type', '?')}"
        )
        logger.info(f"⬅️  DGX RAW BODY: {response.text[:2000]}")

        # Parse JSON BEFORE raise_for_status — the DGX proxy returns JSON
        # error bodies on 502/5xx (e.g. {"error": "Cosmos unreachable"}).
        # The working security.py script does NOT call raise_for_status;
        # it parses the JSON and checks for "error" key. We replicate that.
        try:
            data = response.json()
        except Exception:
            # If the body isn't JSON, THEN raise for HTTP status
            response.raise_for_status()
            raise ValueError(f"DGX returned non-JSON response: {response.text[:200]}")

        # Check for error in JSON body (matches security.py behavior)
        if "error" in data:
            error_msg = data["error"]
            if isinstance(error_msg, dict):
                error_msg = error_msg.get("message", str(error_msg))
            cosmos_down = "cosmos" in str(error_msg).lower() or "unreachable" in str(error_msg).lower()
            if cosmos_down:
                logger.error(f"🔴 DGX Cosmos model is unreachable: {error_msg}")
                return Report(
                    video_id=video_id,
                    summary=f"DGX Cosmos model is unreachable. The Cosmos vision model on the DGX is not running. Error: {error_msg}",
                    overall_compliant=False,
                    analyzed_at=datetime.now(timezone.utc).isoformat(),
                    total_frames_analyzed=1,
                    video_duration=0.0,
                )
            else:
                logger.error(f"🔴 DGX returned error: {error_msg}")
                return Report(
                    video_id=video_id,
                    summary=f"DGX error: {error_msg}",
                    overall_compliant=False,
                    analyzed_at=datetime.now(timezone.utc).isoformat(),
                    total_frames_analyzed=1,
                    video_duration=0.0,
                )

    except sync_requests.Timeout:
        logger.error("DGX request timed out")
        return Report(
            video_id=video_id,
            summary="DGX request timed out (300s limit). The Cosmos+Nemotron pipeline may be overloaded.",
            overall_compliant=False,
            analyzed_at=datetime.now(timezone.utc).isoformat(),
            total_frames_analyzed=1,
            video_duration=0.0,
        )
    except sync_requests.ConnectionError:
        logger.error(f"Cannot connect to DGX proxy at {DGX_PROXY_URL}")
        return Report(
            video_id=video_id,
            summary=f"Cannot connect to DGX Spark at {DGX_PROXY_URL}. Is the proxy (vlm_listener.py) running on the DGX?",
            overall_compliant=False,
            analyzed_at=datetime.now(timezone.utc).isoformat(),
            total_frames_analyzed=1,
            video_duration=0.0,
        )
    except sync_requests.HTTPError as e:
        logger.error(f"DGX HTTP error: {e.response.status_code} — {e.response.text[:500]}")
        return Report(
            video_id=video_id,
            summary=f"DGX HTTP error {e.response.status_code}: {e.response.text[:200]}",
            overall_compliant=False,
            analyzed_at=datetime.now(timezone.utc).isoformat(),
            total_frames_analyzed=1,
            video_duration=0.0,
        )
    except Exception as e:
        logger.error(f"DGX request failed: {e}", exc_info=True)
        return Report(
            video_id=video_id,
            summary=f"DGX error: {str(e)}",
            overall_compliant=False,
            analyzed_at=datetime.now(timezone.utc).isoformat(),
            total_frames_analyzed=1,
            video_duration=0.0,
        )

    # ── Log parsed response ───────────────────────────────────────────
    logger.info(f"⬅️  DGX PARSED JSON: {json.dumps(data, indent=2)[:3000]}")
    report = _parse_dgx_response(data, policy, video_id)
    logger.info(
        f"🟢 DGX analysis: {'COMPLIANT' if report.overall_compliant else 'NON-COMPLIANT'}"
        f" | {len(report.person_summaries)} people | {len(report.incidents)} incidents"
    )
    return report


# ---------------------------------------------------------------------------
# Background DGX health probe — never blocks /health endpoint
# ---------------------------------------------------------------------------
_dgx_health_cache: dict = {"status": "checking"}
_health_probe_started = False


def get_dgx_cached_status() -> dict:
    """Return cached DGX status (never blocks). Starts probe on first call."""
    global _health_probe_started
    if not _health_probe_started:
        _health_probe_started = True
        import threading
        threading.Thread(target=_probe_dgx_sync, daemon=True).start()
    return _dgx_health_cache


def _probe_dgx_sync():
    """Run in a background thread — pings DGX with a socket connect."""
    import socket
    from backend.core.config import DGX_SPARK_IP, DGX_PROXY_PORT

    global _dgx_health_cache
    base_url = f"http://{DGX_SPARK_IP}:{DGX_PROXY_PORT}"

    try:
        sock = socket.create_connection((DGX_SPARK_IP, int(DGX_PROXY_PORT)), timeout=3)
        sock.close()
        _dgx_health_cache = {"status": "connected", "url": base_url}
        logger.info(f"🟢 DGX health probe: connected to {base_url}")
    except (socket.timeout, ConnectionRefusedError, OSError) as e:
        _dgx_health_cache = {"status": "unreachable", "url": base_url, "error": str(e)}
        logger.warning(f"🔴 DGX health probe: unreachable ({e})")


async def check_dgx_health() -> dict:
    """Async check using synchronous requests in a thread."""
    from backend.core.config import DGX_SPARK_IP, DGX_PROXY_PORT

    base_url = f"http://{DGX_SPARK_IP}:{DGX_PROXY_PORT}"

    def _check():
        try:
            r = sync_requests.get(f"{base_url}/health", timeout=3)
            if r.status_code in [200, 404]:
                return {"status": "connected", "url": base_url}
        except Exception:
            pass
        return {"status": "unreachable", "url": base_url, "error": "Timeout or connection refused"}

    return await asyncio.to_thread(_check)
