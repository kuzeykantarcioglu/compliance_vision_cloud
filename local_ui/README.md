# Compliance Vision — Local UI

A web-based interface for the security badge detection system. Wraps the existing `security.py` logic into a modern UI that lets you customize all model inputs in real-time.

## Quick Start

```bash
cd local_ui
pip install -r requirements.txt
python app.py
```

Then open **http://localhost:8080** in your browser.

## Features

- **Live webcam preview** in the browser (no OpenCV window needed)
- **Customizable settings** — server IP, port, model path, FPS, clip duration, tokens, temperature
- **Editable prompt** — modify the system prompt or choose from templates (Badge Detection, Safety/PPE, Crowd Monitoring, General Compliance)
- **Auto-monitoring mode** — continuously captures and analyzes clips
- **Manual capture** — one-click capture and analyze
- **Video upload** — analyze pre-recorded video files
- **Analysis history** — browse past results with click-to-view
- **Live stats** — clip count and alert counter in the header
- **Connection status** — real-time DGX proxy health indicator

## Architecture

```
Browser (webcam + UI)  →  FastAPI backend (app.py)  →  DGX Proxy  →  Cosmos + Nemotron
```

- The **browser** handles webcam capture via `getUserMedia` + `MediaRecorder`
- Recorded clips are sent as base64 to the **FastAPI backend**
- The backend forwards them to your **DGX proxy** and returns the compliance report
- Results are displayed in a rich UI with color-coded status badges

## API Endpoints

| Endpoint | Method | Description |
|---|---|---|
| `/` | GET | Serves the web UI |
| `/api/config` | GET | Get current configuration |
| `/api/config` | POST | Update configuration |
| `/api/config/reset` | POST | Reset to defaults |
| `/api/connection` | GET | Test DGX proxy connection |
| `/api/analyze` | POST | Analyze a base64 video clip |
| `/api/analyze-upload` | POST | Analyze an uploaded video file |
| `/api/stats` | GET | Get session statistics |
| `/api/history` | GET | Get analysis history |
| `/api/stats/reset` | POST | Clear stats and history |
| `/ws` | WebSocket | Real-time analysis channel |

## Prompt Templates

Switch between pre-built templates in the **Prompt** tab:

- **Badge Detection** — TreeHacks badge PCB identification
- **Safety / PPE** — Hard hat, goggles, vest compliance
- **Crowd Monitoring** — People count, density, overcrowding
- **General Compliance** — Open-ended scene analysis
