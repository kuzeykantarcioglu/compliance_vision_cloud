# Compliance Vision

**Define any compliance policy in plain English. Point it at any camera. Get structured, audit-ready reports automatically.**

Compliance Vision is an AI-powered video compliance monitoring platform that uses OpenAI's GPT-4o vision, GPT-4o-mini, and Whisper to analyze video feeds against user-defined policies in real time.

---

## Features

- **Natural language policies** — describe what to check in plain English (PPE, badges, authorized personnel, restricted areas, etc.)
- **File & webcam input** — upload a video file or monitor a live webcam feed
- **Visual reference matching** — upload photos of authorized people, badge designs, or specific objects and the AI checks for them
- **Audio analysis** — toggle Whisper transcription to enforce speech-based rules (safety briefings, prohibited language, etc.)
- **Real-time monitoring** — pipelined webcam processing overlaps recording and analysis for near-real-time results
- **Structured reports** — every analysis produces JSON reports with verdicts, severity, timestamps, evidence screenshots, and recommendations
- **Polly AI assistant** — conversational policy builder that generates policies from natural language
- **Preset management** — save, load, import, and export policy configurations

---

## Architecture

```
┌─────────────┐     ┌──────────────────────────────────────────────┐
│   Frontend   │     │                  Backend                     │
│  React/Vite  │────▶│  FastAPI                                     │
│  TypeScript  │     │                                              │
│  Tailwind    │     │  Video ──▶ Change Detection ──▶ Keyframes    │
│              │     │                                  │           │
│              │◀────│  Keyframes ──▶ GPT-4o Vision ──▶ Observations│
│              │     │  Audio ─────▶ Whisper ──────────▶ Transcript  │
│              │     │                                  │           │
│              │     │  Observations + Transcript ──▶ GPT-4o-mini   │
│              │     │                                  │           │
│              │     │                              ──▶ Report      │
└─────────────┘     └──────────────────────────────────────────────┘
```

---

## Prerequisites

- **Python 3.10+**
- **Node.js 18+**
- **ffmpeg** (required for audio extraction / Whisper)
- **OpenAI API key** with access to GPT-4o, GPT-4o-mini, and Whisper

---

## Setup

### 1. Clone the repository

```bash
git clone https://github.com/kuzeykantarcioglu/compliance_vision_cloud.git
cd compliance_vision_cloud
```

### 2. Configure environment

```bash
cp .env.example .env
```

Edit `.env` and add your OpenAI API key:

```
OPENAI_API_KEY=sk-your-key-here
```

### 3. Install backend dependencies

```bash
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r backend/requirements.txt
```

### 4. Install frontend dependencies

```bash
cd frontend
npm install
cd ..
```

### 5. Install ffmpeg (if not already installed)

```bash
# macOS
brew install ffmpeg

# Ubuntu/Debian
sudo apt install ffmpeg
```

---

## Running

Open **two terminals** from the project root:

**Terminal 1 — Backend** (runs on port 8000):

```bash
source .venv/bin/activate
uvicorn backend.main:app --reload --host 0.0.0.0 --port 8000
```

**Terminal 2 — Frontend** (runs on port 5173):

```bash
cd frontend
npm run dev
```

Open **http://localhost:5173** in your browser.

---

## Usage

### File analysis

1. Switch to **File** mode in the side panel
2. Upload a video file (MP4, WebM, etc.)
3. Configure a policy — either:
   - Load a **built-in preset** (PPE Compliance, Badge & Access Control, etc.)
   - Write your own rules using the rule builder
   - Use the **Polly** tab to describe what you want in natural language
4. Click **Analyze Video**
5. View the structured report in the main panel (verdicts, evidence screenshots, timeline, recommendations)

### Live webcam monitoring

1. Switch to **Webcam** mode
2. Allow camera access when prompted
3. Configure your policy
4. Click **Start Monitoring**
5. The system records 8-second chunks, overlapping recording and analysis for near-real-time results
6. View the live incident feed, transcript, and chunk reports as they stream in
7. Click **Stop Monitoring** when done — export the full session as JSON

### Visual references

1. Go to the **References** tab
2. Upload images of authorized people, approved badge designs, or specific objects
3. Categorize them (People / Badges / Objects) and configure per-reference checks
4. Go back to the **Policy** tab — toggle on the references you want active under **Reference Rules**
5. Only enabled references are sent to the AI during analysis

### Audio analysis

1. Toggle **Audio Analysis (Whisper)** on in the Policy tab
2. Add `speech` type rules (e.g., "Safety briefing must be delivered verbally")
3. The system transcribes audio in parallel with visual analysis and evaluates speech rules separately

### Polly (AI policy assistant)

1. Go to the **Polly** tab
2. Describe what you want to monitor in natural language (e.g., "I need to check that everyone in a warehouse is wearing a hard hat and safety vest")
3. Polly generates a complete policy with rules, severity levels, and context
4. Click **Apply this policy** to load it into the Policy tab

---

## Project structure

```
├── backend/
│   ├── core/config.py          # Environment config, API keys
│   ├── models/schemas.py       # Pydantic data models
│   ├── routers/
│   │   ├── analyze.py          # POST /analyze/ — full pipeline endpoint
│   │   └── polly.py            # POST /polly/chat — AI policy assistant
│   └── services/
│       ├── video.py            # Change detection + keyframe extraction
│       ├── vlm.py              # GPT-4o vision analysis
│       ├── policy.py           # GPT-4o-mini policy evaluation + report
│       ├── speech_policy.py    # Speech-only rule evaluation
│       └── whisper.py          # Audio extraction + transcription
├── frontend/
│   └── src/
│       ├── App.tsx             # Main app layout + monitoring loop
│       ├── api.ts              # Backend API client
│       ├── types.ts            # TypeScript interfaces
│       └── components/
│           ├── PolicyConfig    # Rule builder + presets + reference rules
│           ├── ReferencesPanel # Visual reference management
│           ├── VideoInput      # File upload + webcam capture
│           ├── ReportView      # File analysis report display
│           ├── LiveReportView  # Real-time monitoring dashboard
│           ├── PollyChat       # AI policy assistant chat
│           └── PipelineStatus  # Animated pipeline progress
├── scene_detection.py          # OpenCV change detection engine
├── .env.example                # Environment template
└── .gitignore
```

---

## API endpoints

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/health` | Health check + API key status |
| `POST` | `/analyze/` | Full video analysis pipeline (multipart: video + policy JSON) |
| `POST` | `/polly/chat` | AI policy assistant conversation |

---

## Key configuration

The change detection engine can be tuned via `backend/services/video.py`:

| Parameter | Default | Description |
|-----------|---------|-------------|
| `sample_interval` | `0.3s` | How often to sample frames (lower = catches faster events) |
| `change_threshold` | `0.10` | Sensitivity 0-1 (lower = more sensitive) |
| `min_change_interval` | `0.5s` | Debounce between captures |
| `max_gap` | `10.0s` | Max seconds without a keyframe |

---

## License

MIT
