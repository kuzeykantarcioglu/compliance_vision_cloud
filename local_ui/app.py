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


class AnalyzeRequest(BaseModel):
    video_base64: str
    prompt_override: Optional[str] = None
    max_tokens_override: Optional[int] = None
    temperature_override: Optional[float] = None


# ─── Helper Functions ────────────────────────────────────────────────────────

def get_proxy_url():
    return f"http://{config['spark_ip']}:{config['proxy_port']}{config['endpoint_path']}"


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
    """Convert webm/any video bytes to mp4 using OpenCV"""
    # Write input to temp file
    with tempfile.NamedTemporaryFile(suffix=".webm", delete=False) as tmp_in:
        tmp_in.write(video_bytes)
        tmp_in_path = tmp_in.name

    tmp_out_path = tmp_in_path.replace(".webm", ".mp4")

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
    logger.info(f"DGX response: {json.dumps(data)[:500]}")

    if "error" in data:
        raise RuntimeError(data["error"])
    return data


def format_report(report):
    """Format compliance report for display"""
    status = report.get("overall_status", "unknown").upper()
    violations = report.get("violations", [])

    return {
        "status": status,
        "violation_count": len(violations),
        "violations": violations,
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
