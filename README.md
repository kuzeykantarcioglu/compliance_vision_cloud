<div align="center">

# Agent 00Vision

### AI-Powered Video Compliance Monitoring

[![Python](https://img.shields.io/badge/Python-3.11%2B-blue)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115-green)](https://fastapi.tiangolo.com/)
[![React](https://img.shields.io/badge/React-19-61dafb)](https://react.dev/)
[![NVIDIA](https://img.shields.io/badge/NVIDIA-DGX%20Spark-76b900)](https://www.nvidia.com/en-us/data-center/dgx-spark/)

**Define any compliance policy in plain English. Point it at any camera. Get structured, audit-ready reports.**

</div>

---

## Quick Start

**Prerequisites:** Python 3.11+, Node.js 18+, an OpenAI API key

```bash
git clone https://github.com/kuzeykantarcioglu/treehacks2026.git
cd treehacks2026

# Add your API key
echo "OPENAI_API_KEY=sk-your-key-here" > .env

# Run everything
./run.sh
```

That's it. The script creates a virtualenv, installs dependencies, and starts both servers.

- **Frontend:** http://localhost:5173
- **Backend API:** http://localhost:8082
- **API Docs:** http://localhost:8082/docs

Press `Ctrl+C` to stop all services.

### Manual Setup

If you prefer to run things separately:

```bash
# Backend (terminal 1)
python3 -m venv venv && source venv/bin/activate
pip install -r backend/requirements.txt
PYTHONPATH=$(pwd) uvicorn backend.main:app --reload --host 0.0.0.0 --port 8082

# Frontend (terminal 2)
cd frontend && npm install && npm run dev
```

---

## What It Does

Agent 00Vision watches video feeds and enforces compliance rules you write in plain English.

```
"All personnel must wear a hard hat and yellow safety vest"
     |
     v
  AI watches the camera feed
     |
     v
  Structured report: 2 violations detected, timestamps, severity, recommendations
```

**Two modes of operation:**

| Mode | Input | Use Case |
|------|-------|----------|
| **Live monitoring** | Webcam feed | Real-time compliance with continuous alerts |
| **File analysis** | Uploaded video | Batch processing with full report |

**Two AI backends:**

| Provider | Models | Data Residency |
|----------|--------|----------------|
| **OpenAI (cloud)** | GPT-4o Vision + GPT-4o-mini + Whisper | Cloud |
| **NVIDIA DGX Spark (local)** | Cosmos-Reason2 8B + Nemotron-3-Nano 30B | On-premise |

---

## Features

- **Policy-as-prompt** — Write any compliance rule in English, no model training needed
- **Dual-mode compliance** — Incident mode (alert every violation) vs. Checklist mode (check once per validity period) to prevent alert fatigue
- **Smart frame sampling** — Change detection reduces frames sent to the VLM by 80-95%, making the product economically viable
- **Reference image matching** — Upload photos of authorized personnel or badges for identity verification
- **Audio compliance** — Whisper transcription for speech-based rules (safety briefings, verbal confirmations)
- **Structured reports** — Machine-readable JSON output with severity, timestamps, and recommendations
- **AI policy assistant** — Chatbot that helps you build compliance policies

---

## Architecture

```
Frontend (React + TypeScript + Vite + Tailwind)
  |
  | /api proxy (Vite -> :8082)
  v
Backend (FastAPI)
  |
  |-- POST /analyze/        Full video pipeline (sync)
  |-- POST /analyze/frame   Single frame analysis (webcam)
  |-- POST /polly/chat      AI policy assistant
  |-- GET  /health          System status
  |
  v
Processing Pipeline
  1. Frame Extraction + Change Detection (OpenCV)
  2. Visual Analysis (GPT-4o Vision or Cosmos-Reason2)
  3. Audio Transcription (Whisper) [optional]
  4. Policy Evaluation (GPT-4o-mini or Nemotron-3-Nano)
  5. Report Generation (structured JSON)
```

---

## Project Structure

```
treehacks2026/
├── backend/
│   ├── main.py                 # FastAPI entry point
│   ├── core/config.py          # Environment + OpenAI client config
│   ├── models/schemas.py       # Pydantic data models
│   ├── routers/
│   │   ├── analyze.py          # /analyze, /analyze/frame endpoints
│   │   ├── async_analyze.py    # /async/analyze (requires Redis)
│   │   ├── polly.py            # /polly/chat AI assistant
│   │   └── websocket.py        # WebSocket for task updates
│   └── services/
│       ├── video.py            # Frame extraction + keyframe sampling
│       ├── vlm.py              # GPT-4o Vision calls
│       ├── policy.py           # Compliance evaluation engine
│       ├── dgx.py              # NVIDIA DGX Spark integration
│       ├── whisper.py          # Audio transcription
│       └── api_utils.py        # Retry logic + rate limiting
├── frontend/
│   ├── src/
│   │   ├── App.tsx             # Main app component
│   │   ├── api.ts              # Backend API client
│   │   └── components/
│   │       ├── PolicyConfig.tsx      # Rule builder UI
│   │       ├── LiveReportView.tsx    # Real-time monitoring
│   │       ├── ReportView.tsx        # Analysis results
│   │       ├── VideoInput.tsx        # Webcam/file input
│   │       ├── ReferenceImages.tsx   # Reference photo management
│   │       ├── PollyChat.tsx         # AI policy assistant
│   │       └── DualModeReport.tsx    # Incident vs. Checklist display
│   └── vite.config.ts          # Vite config (proxies /api -> :8082)
├── scene_detection.py          # OpenCV change detection engine
├── run.sh                      # Single script to start everything
├── stop.sh                     # Stop all services
└── .env                        # OPENAI_API_KEY (not committed)
```

---

## Configuration

```bash
# .env
OPENAI_API_KEY=sk-your-key-here

# Optional — only needed for async features
REDIS_URL=redis://localhost:6379/0

# Optional — DGX Spark local inference
DGX_SPARK_IP=10.19.176.53
DGX_PROXY_PORT=8001
```

---

## Built With

**AI/ML:** OpenAI GPT-4o Vision, GPT-4o-mini, Whisper, NVIDIA Cosmos-Reason2 8B, NVIDIA Nemotron-3-Nano 30B

**Backend:** Python, FastAPI, OpenCV, Celery, Redis, WebSockets

**Frontend:** React 19, TypeScript, Vite, Tailwind CSS

**Infrastructure:** NVIDIA DGX Spark, vLLM, Ollama

---

<div align="center">

**Built at TreeHacks 2026**

</div>
