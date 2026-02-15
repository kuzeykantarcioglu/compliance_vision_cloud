#!/usr/bin/env python3
"""
Compliance Vision - Local UI Backend
FastAPI server that wraps the security badge detection logic
and exposes it through a modern web interface.
"""

import warnings
warnings.filterwarnings("ignore", category=UserWarning)

import os
import base64
import tempfile
import time
import json
import asyncio
import logging
from typing import Optional
from pathlib import Path

import cv2
import requests

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("compliance-vision")
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, UploadFile, File, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, FileResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

app = FastAPI(title="Compliance Vision Local UI")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ─── Default Configuration ───────────────────────────────────────────────────

DEFAULT_CONFIG = {
    "spark_ip": "10.19.176.53",
    "proxy_port": 8001,
    "endpoint_path": "/v1/analyze_frame_sync",
    "model_id": "/home/asus/.cache/huggingface/hub/models--nvidia--Cosmos-Reason2-8B/snapshots/7d6a645088b550bbd45daaf782e2430bba9c82bb",
    "prompt": """You are a security camera AI for TreeHacks 2026 hackathon at Stanford University.

THE OFFICIAL TREEHACKS BADGE:
- Christmas tree / pine tree shaped 
- Has "TREE HACKS" and "2026" text in white
- Worn around neck or held in hand

JOB: For each person in the video, determine if they have a TreeHacks badge or not.

RESPOND IN THIS EXACT JSON FORMAT:
{
  "people_count": <number>,
  "people": [
    {
      "person": "Person 1",
      "facing_camera": true or false,
      "badge_visible": true or false,
      "description": "brief appearance description and text on badge"
    }
  ]
}

RULES:
- If a person is NOT facing the camera, set facing_camera to false and badge_visible to false.
- Only set badge_visible to true if you can clearly see the TreeHacks PCB badge.
- If no people are visible, return: {"people_count": 0, "people": []}
- Return ONLY the JSON, no other text.""",
    "max_tokens": 2048,
    "temperature": 0.6,
    "clip_duration": 3,
    "fps": 4,
    "auto_analyze": True,
    "alert_email": "userdorukhan@gmail.com",
    "email_alerts_enabled": True,
    "resend_api_key": "",
    "email_from": "Compliance Vision <onboarding@resend.dev>",
    "location": "Stanford University - TreeHacks 2026",
}

# Runtime state
config = {**DEFAULT_CONFIG}
session_stats = {"clips_analyzed": 0, "alerts": 0, "start_time": None}
analysis_history = []


# ─── Models ──────────────────────────────────────────────────────────────────

class ConfigUpdate(BaseModel):
    spark_ip: Optional[str] = None
    proxy_port: Optional[int] = None
    endpoint_path: Optional[str] = None
    model_id: Optional[str] = None
    prompt: Optional[str] = None
    max_tokens: Optional[int] = None
    temperature: Optional[float] = None
    clip_duration: Optional[int] = None
    fps: Optional[int] = None
    auto_analyze: Optional[bool] = None
    alert_email: Optional[str] = None
    email_alerts_enabled: Optional[bool] = None
    resend_api_key: Optional[str] = None
    email_from: Optional[str] = None
    location: Optional[str] = None


class AnalyzeRequest(BaseModel):
    video_base64: str
    prompt_override: Optional[str] = None
    max_tokens_override: Optional[int] = None
    temperature_override: Optional[float] = None


# ─── Helper Functions ────────────────────────────────────────────────────────

def get_proxy_url():
    return f"http://{config['spark_ip']}:{config['proxy_port']}{config['endpoint_path']}"


def send_alert_email(report: dict):
    """Send an email alert via Resend API when violations are detected."""
    if not config.get("email_alerts_enabled"):
        return
    recipient = config.get("alert_email", "").strip()
    api_key = config.get("resend_api_key", "").strip()
    email_from = config.get("email_from", "Compliance Vision <onboarding@resend.dev>").strip()
    if not recipient:
        logger.warning("Email alerts enabled but no recipient configured")
        return
    if not api_key:
        logger.warning("Email alerts enabled but no Resend API key configured")
        return

    location = config.get("location", "Unknown Location")
    violations = report.get("violations", [])
    people = report.get("people", [])
    timestamp = report.get("timestamp", time.strftime("%Y-%m-%d %H:%M:%S"))
    status = report.get("status", "UNKNOWN")
    v_count = report.get("violation_count", len(violations))

    subject = f"\U0001f6a8 Security Alert \u2014 {v_count} Violation(s) at {location}"

    # Build HTML email body
    violation_rows = ""
    for v in violations:
        violation_rows += f"""
        <tr>
            <td style="padding:8px 12px;border-bottom:1px solid #eee;font-weight:600;color:#dc2626;">{v.get('subject', 'Unknown')}</td>
            <td style="padding:8px 12px;border-bottom:1px solid #eee;">{v.get('rule', 'Violation')}</td>
            <td style="padding:8px 12px;border-bottom:1px solid #eee;color:#666;">{v.get('description', '')}</td>
        </tr>"""

    people_rows = ""
    for p in people:
        badge_color = "#16a34a" if p.get("compliant") else "#dc2626"
        badge_text = "Compliant" if p.get("compliant") else "Violation"
        if p.get("facing_camera") is False:
            badge_color = "#ca8a04"
            badge_text = "Not Facing"
        people_rows += f"""
        <tr>
            <td style="padding:6px 12px;border-bottom:1px solid #f0f0f0;">{p.get('person', 'Person')}</td>
            <td style="padding:6px 12px;border-bottom:1px solid #f0f0f0;color:{badge_color};font-weight:600;">{badge_text}</td>
            <td style="padding:6px 12px;border-bottom:1px solid #f0f0f0;color:#666;font-size:13px;">{p.get('description', '')}</td>
        </tr>"""

    html_body = f"""
    <div style="font-family:Arial,sans-serif;max-width:600px;margin:0 auto;">
        <div style="background:#dc2626;color:white;padding:16px 20px;border-radius:8px 8px 0 0;">
            <h2 style="margin:0;font-size:18px;">\U0001f6a8 Compliance Violation Detected</h2>
        </div>
        <div style="background:#fff;border:1px solid #e5e7eb;border-top:none;padding:20px;border-radius:0 0 8px 8px;">
            <table style="width:100%;margin-bottom:16px;">
                <tr><td style="color:#666;padding:4px 0;">Location:</td><td style="font-weight:600;">{location}</td></tr>
                <tr><td style="color:#666;padding:4px 0;">Time:</td><td>{timestamp}</td></tr>
                <tr><td style="color:#666;padding:4px 0;">Status:</td><td style="color:#dc2626;font-weight:700;">{status}</td></tr>
                <tr><td style="color:#666;padding:4px 0;">Violations:</td><td style="font-weight:600;">{v_count}</td></tr>
            </table>

            <h3 style="font-size:14px;color:#333;border-bottom:2px solid #dc2626;padding-bottom:6px;">Violations</h3>
            <table style="width:100%;border-collapse:collapse;margin-bottom:16px;">
                <tr style="background:#fef2f2;">
                    <th style="padding:8px 12px;text-align:left;font-size:12px;color:#666;">Subject</th>
                    <th style="padding:8px 12px;text-align:left;font-size:12px;color:#666;">Rule</th>
                    <th style="padding:8px 12px;text-align:left;font-size:12px;color:#666;">Description</th>
                </tr>
                {violation_rows}
            </table>

            {f'''
            <h3 style="font-size:14px;color:#333;border-bottom:2px solid #6366f1;padding-bottom:6px;">All Detected People</h3>
            <table style="width:100%;border-collapse:collapse;">
                <tr style="background:#f8fafc;">
                    <th style="padding:6px 12px;text-align:left;font-size:12px;color:#666;">Person</th>
                    <th style="padding:6px 12px;text-align:left;font-size:12px;color:#666;">Status</th>
                    <th style="padding:6px 12px;text-align:left;font-size:12px;color:#666;">Description</th>
                </tr>
                {people_rows}
            </table>
            ''' if people_rows else ''}

            <p style="margin-top:20px;font-size:12px;color:#999;border-top:1px solid #eee;padding-top:12px;">
                Sent by Compliance Vision &mdash; TreeHacks 2026
            </p>
        </div>
    </div>
    """

    try:
        resp = requests.post(
            "https://api.resend.com/emails",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json={
                "from": email_from,
                "to": [recipient],
                "subject": subject,
                "html": html_body,
            },
            timeout=10,
        )
        if resp.status_code in (200, 201):
            logger.info(f"Alert email sent to {recipient} via Resend")
        else:
            logger.error(f"Resend API error {resp.status_code}: {resp.text}")
    except Exception as e:
        logger.error(f"Failed to send alert email: {e}")


def check_connection():
    """Check if DGX proxy is reachable"""
    try:
        resp = requests.get(
            f"http://{config['spark_ip']}:{config['proxy_port']}/health",
            timeout=5
        )
        return resp.status_code in [200, 404]
    except Exception:
        return False


def convert_webm_to_mp4(video_bytes: bytes) -> bytes:
    """Convert any video bytes to mp4 using OpenCV.
    Detects format from file signature to use correct temp extension."""
    # Detect format from magic bytes
    if video_bytes[:4] == b'\x1aE\xdf\xa3':
        ext = ".webm"
    elif video_bytes[4:8] == b'ftyp':
        ext = ".mp4"  # Already mp4, still re-encode for consistency
    elif video_bytes[:4] == b'RIFF':
        ext = ".avi"
    else:
        ext = ".mp4"  # Default

    with tempfile.NamedTemporaryFile(suffix=ext, delete=False) as tmp_in:
        tmp_in.write(video_bytes)
        tmp_in_path = tmp_in.name

    tmp_out_path = tmp_in_path.rsplit(".", 1)[0] + "_out.mp4"

    try:
        cap = cv2.VideoCapture(tmp_in_path)
        if not cap.isOpened():
            logger.error("Cannot open input video for conversion")
            return video_bytes  # Return original if conversion fails

        fps = cap.get(cv2.CAP_PROP_FPS) or 4
        w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))

        writer = cv2.VideoWriter(tmp_out_path, cv2.VideoWriter_fourcc(*"mp4v"), fps, (w, h))
        frame_count = 0
        while True:
            ret, frame = cap.read()
            if not ret:
                break
            writer.write(frame)
            frame_count += 1

        cap.release()
        writer.release()

        logger.info(f"Converted video: {frame_count} frames, {w}x{h} @ {fps:.0f}fps")

        with open(tmp_out_path, "rb") as f:
            return f.read()
    except Exception as e:
        logger.error(f"Video conversion failed: {e}")
        return video_bytes
    finally:
        for p in [tmp_in_path, tmp_out_path]:
            try:
                os.unlink(p)
            except OSError:
                pass


def analyze_video(video_b64: str, prompt: str, max_tokens: int, temperature: float):
    """Send video to DGX proxy and get analysis back"""
    proxy_url = get_proxy_url()
    logger.info(f"Sending analysis request to {proxy_url}")

    # Convert webm to mp4 (browser MediaRecorder captures webm)
    try:
        raw_bytes = base64.b64decode(video_b64)
        logger.info(f"Input video size: {len(raw_bytes)} bytes")
        mp4_bytes = convert_webm_to_mp4(raw_bytes)
        mp4_b64 = base64.b64encode(mp4_bytes).decode()
        logger.info(f"Converted mp4 size: {len(mp4_bytes)} bytes")
    except Exception as e:
        logger.error(f"Video conversion error: {e}")
        mp4_b64 = video_b64  # Fallback to original

    payload = {
        "model": config["model_id"],
        "messages": [
            {
                "role": "user",
                "content": [
                    {
                        "type": "video_url",
                        "video_url": {"url": f"data:video/mp4;base64,{mp4_b64}"}
                    },
                    {
                        "type": "text",
                        "text": prompt
                    }
                ]
            }
        ],
        "max_tokens": max_tokens,
        "temperature": temperature
    }

    logger.info(f"Payload size: {len(json.dumps(payload)) / 1024:.0f} KB")

    response = requests.post(proxy_url, json=payload, timeout=120)
    logger.info(f"DGX response status: {response.status_code}")

    data = response.json()
    logger.info(f"DGX response keys: {list(data.keys()) if isinstance(data, dict) else type(data)}")
    logger.info(f"DGX response: {json.dumps(data)[:1000]}")

    if "error" in data:
        raise RuntimeError(data["error"])
    return data


def format_report(report):
    """Format compliance report for display.
    Handles both direct Nemotron output and OpenAI-wrapped format.
    Also extracts Cosmos people data when available."""
    import re as _re
    compliance = None
    people = []
    people_count = 0
    raw_content = ""

    # Case 1: Direct Nemotron format {overall_status, violations}
    if "overall_status" in report:
        compliance = report
    # Case 2: OpenAI chat-completion wrapper {choices: [{message: {content: "..."}}]}
    elif "choices" in report:
        try:
            raw_content = report["choices"][0]["message"]["content"]
            # Extract JSON from possible thinking text
            match = _re.search(r'\{[\s\S]*\}', raw_content)
            if match:
                compliance = json.loads(match.group())
        except Exception as e:
            logger.warning(f"Could not parse choices content: {e}")

    if compliance and "overall_status" in compliance:
        status = compliance["overall_status"].upper()
        violations = compliance.get("violations", [])
    else:
        status = "UNKNOWN"
        violations = []

    # --- Extract Cosmos people data from all possible locations ---
    # 1. Directly in response (if proxy forwards cosmos_output)
    if "people" in report and isinstance(report["people"], list):
        people = report["people"]
        people_count = report.get("people_count", len(people))
    elif "cosmos_output" in report:
        cosmos = report["cosmos_output"]
        if isinstance(cosmos, dict):
            people = cosmos.get("people", [])
            people_count = cosmos.get("people_count", len(people))
    # 2. Parse Cosmos JSON from Nemotron thinking text (between <think> and </think>)
    elif raw_content:
        think_match = _re.search(r'<think>([\s\S]*?)</think>', raw_content)
        if think_match:
            think_text = think_match.group(1)
            cosmos_match = _re.search(r'\{[\s\S]*?"people"\s*:\s*\[[\s\S]*?\]\s*\}', think_text)
            if cosmos_match:
                try:
                    cosmos_data = json.loads(cosmos_match.group())
                    people = cosmos_data.get("people", [])
                    people_count = cosmos_data.get("people_count", len(people))
                except json.JSONDecodeError:
                    pass
    # 3. If compliance itself has people (Cosmos format passed through)
    if not people and compliance and "people" in compliance:
        people = compliance.get("people", [])
        people_count = compliance.get("people_count", len(people))

    # Build violation subjects set for cross-referencing
    violation_subjects = {v.get("subject", "").lower() for v in violations}

    # If we have people data, mark each person's compliance status
    enriched_people = []
    for p in people:
        person_name = p.get("person", "")
        is_violator = person_name.lower() in violation_subjects
        enriched_people.append({
            **p,
            "compliant": not is_violator,
            "violation": next((v for v in violations if v.get("subject", "").lower() == person_name.lower()), None)
        })

    return {
        "status": status,
        "violation_count": len(violations),
        "violations": violations,
        "people": enriched_people,
        "people_count": people_count or len(enriched_people),
        "raw": report,
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
    }


# ─── Serve Static Files (must be before routes) ─────────────────────────────

static_dir = Path(__file__).parent / "static"
if not static_dir.exists():
    static_dir.mkdir(parents=True, exist_ok=True)
app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")


# ─── API Routes ──────────────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
async def serve_ui():
    html_path = Path(__file__).parent / "static" / "index.html"
    return FileResponse(html_path, media_type="text/html")


@app.get("/api/config")
async def get_config():
    return config


@app.post("/api/config")
async def update_config(update: ConfigUpdate):
    for key, value in update.dict(exclude_none=True).items():
        config[key] = value
    return {"status": "ok", "config": config}


@app.post("/api/config/reset")
async def reset_config():
    global config
    config = {**DEFAULT_CONFIG}
    return {"status": "ok", "config": config}


@app.get("/api/connection")
async def test_connection():
    connected = check_connection()
    return {
        "connected": connected,
        "proxy_url": get_proxy_url(),
        "spark_ip": config["spark_ip"],
        "port": config["proxy_port"],
    }


@app.post("/api/analyze")
async def analyze(req: AnalyzeRequest):
    prompt = req.prompt_override or config["prompt"]
    max_tokens = req.max_tokens_override or config["max_tokens"]
    temperature = req.temperature_override or config["temperature"]

    try:
        raw_report = analyze_video(req.video_base64, prompt, max_tokens, temperature)
        report = format_report(raw_report)

        # Update session stats
        session_stats["clips_analyzed"] += 1
        if report["violation_count"] > 0:
            session_stats["alerts"] += 1
            # Send email alert in background
            import threading
            threading.Thread(target=send_alert_email, args=(report,), daemon=True).start()

        # Keep history (last 50)
        analysis_history.insert(0, report)
        if len(analysis_history) > 50:
            analysis_history.pop()

        return report

    except requests.Timeout:
        raise HTTPException(status_code=504, detail="Analysis timed out (120s)")
    except requests.ConnectionError:
        raise HTTPException(status_code=502, detail="Cannot reach DGX proxy")
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Analysis error: {str(e)}")


@app.post("/api/analyze-upload")
async def analyze_upload(file: UploadFile = File(...)):
    """Analyze an uploaded video file"""
    contents = await file.read()
    video_b64 = base64.b64encode(contents).decode()

    try:
        raw_report = analyze_video(video_b64, config["prompt"], config["max_tokens"], config["temperature"])
        report = format_report(raw_report)
        session_stats["clips_analyzed"] += 1
        if report["violation_count"] > 0:
            session_stats["alerts"] += 1
            import threading
            threading.Thread(target=send_alert_email, args=(report,), daemon=True).start()
        analysis_history.insert(0, report)
        if len(analysis_history) > 50:
            analysis_history.pop()
        return report
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/stats")
async def get_stats():
    return {**session_stats, "history_count": len(analysis_history)}


@app.get("/api/history")
async def get_history():
    return analysis_history


@app.post("/api/stats/reset")
async def reset_stats():
    global session_stats, analysis_history
    session_stats = {"clips_analyzed": 0, "alerts": 0, "start_time": None}
    analysis_history = []
    return {"status": "ok"}


# ─── WebSocket for live updates ──────────────────────────────────────────────

connected_clients: list[WebSocket] = []


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    connected_clients.append(websocket)
    try:
        while True:
            data = await websocket.receive_text()
            # Client can send video frames for analysis via WebSocket
            try:
                msg = json.loads(data)
                if msg.get("type") == "analyze":
                    video_b64 = msg["video_base64"]
                    prompt = msg.get("prompt", config["prompt"])
                    max_tokens = msg.get("max_tokens", config["max_tokens"])
                    temperature = msg.get("temperature", config["temperature"])

                    raw_report = analyze_video(video_b64, prompt, max_tokens, temperature)
                    report = format_report(raw_report)

                    session_stats["clips_analyzed"] += 1
                    if report["violation_count"] > 0:
                        session_stats["alerts"] += 1
                    analysis_history.insert(0, report)
                    if len(analysis_history) > 50:
                        analysis_history.pop()

                    await websocket.send_text(json.dumps({
                        "type": "result",
                        "data": report
                    }))
                elif msg.get("type") == "ping":
                    await websocket.send_text(json.dumps({"type": "pong"}))
            except Exception as e:
                await websocket.send_text(json.dumps({
                    "type": "error",
                    "message": str(e)
                }))
    except WebSocketDisconnect:
        connected_clients.remove(websocket)


# ─── Main ────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn
    print("\n" + "=" * 55)
    print("  🛡️  Compliance Vision - Local UI")
    print("=" * 55)
    print(f"  Open http://localhost:3000 in your browser")
    print(f"  DGX Proxy: {get_proxy_url()}")
    print("=" * 55 + "\n")
    uvicorn.run(app, host="0.0.0.0", port=3000)
