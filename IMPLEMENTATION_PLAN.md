# Video Compliance Monitoring System — Implementation Plan

> YC-style product: Video input → VLM analysis → Policy evaluation → Structured reports.
> **Deployment modes:** Cloud (OpenAI / Brev) or Local (DGX on-prem) — toggled per customer.
> Future: Whisper transcript layer.

---
## TODO: Need to add person tracking. 
## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                              UI LAYER                                        │
│  Video Config │ Policy Config │ Live View │ Reports │ [Whisper Toggle]       │
└─────────────────────────────────────────────────────────────────────────────┘
                                      │
                                      ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                           INGESTION LAYER                                    │
│  Video File Upload / Webcam Stream                                           │
└─────────────────────────────────────────────────────────────────────────────┘
                                      │
                                      ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                           VLM LAYER (Vision)                                 │
│  Frame sampling → OpenAI GPT-4V / Brev VLM → "What do I see?" output         │
└─────────────────────────────────────────────────────────────────────────────┘
                                      │
                                      ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                           POLICY LAYER (LLM)                                 │
│  Policy rules + VLM output → Compliant / Non-compliant decisions             │
└─────────────────────────────────────────────────────────────────────────────┘
                                      │
                                      ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                           REPORT LAYER (LLM)                                 │
│  Decisions + context → Structured JSON schema                                │
└─────────────────────────────────────────────────────────────────────────────┘
                                      │
                                      ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                           UI DISPLAY                                         │
│  JSON → Cards / Timeline / Summary / Export !!!!WHAT ACTION TO TAKE?         │
└─────────────────────────────────────────────────────────────────────────────┘

[Future] Whisper → Transcript → Policy/Report integration (when toggled)

                    ┌──────────────────────────────┐
                    │      DEPLOYMENT MODE TOGGLE   │
                    │  ☁️  Cloud (OpenAI / Brev)     │  ← Building now
                    │  🏢 Local (DGX on-prem)       │  ← Future
                    └──────────────────────────────┘
```

---

## Milestones

### Milestone 0: Project Setup & Environment

**Goal:** Scaffold a runnable app with API keys, env, and basic structure.

| Task | How to Accomplish |
|------|-------------------|
| Choose stack | **Backend:** Node.js + Express or Python + FastAPI. **Frontend:** React + Vite or Next.js. |
| Create repo structure | `backend/`, `frontend/`, `shared/` (types), `docs/` |
| Environment config | `.env.example` with `OPENAI_API_KEY`, `BREV_API_KEY` (optional). Use `dotenv` / similar. |
| API key validation | Health-check endpoint that verifies keys on startup (optional but recommended) |
| Dev scripts | `npm run dev` for frontend + backend concurrently |

**Deliverable:** `npm run dev` starts frontend and backend without errors.

---

### Milestone 1: Video Input Channel (File + Webcam)

**Goal:** Capture video from file or webcam and expose it to the pipeline.

| Task | How to Accomplish |
|------|-------------------|
| **File upload** | Use `<input type="file" accept="video/*">`, `FileReader` / FormData. Backend: `multer` (Node) or `upload_file` (FastAPI). Store temp path or stream. |
| **Webcam capture** | `navigator.mediaDevices.getUserMedia({ video: true })`. Record via MediaRecorder (WebM/Blob) or stream frames to backend. |
| **Unified interface** | Abstract `VideoSource` as `{ type: 'file' | 'webcam', url?: string, stream?: MediaStream }`. |
| **Frame extraction** | Backend: use `ffmpeg` (Node: `fluent-ffmpeg`, Python: `ffmpeg-python`) to extract frames at fixed interval (e.g. 1 FPS). Return paths or base64 for VLM. |
| **Chunk handling** | For long videos, process in chunks (e.g. 30s segments) to avoid timeouts. |

**Deliverable:** API endpoint(s): `POST /video/upload`, `POST /video/webcam-chunk` (optional). Response includes `{ frames: [...], metadata }`.

**Tech notes:**
- ffmpeg: `ffmpeg -i input.mp4 -vf fps=1 -f image2 frame_%04d.png`
- For webcam: can send base64 frames from frontend or use backend capture (e.g. puppeteer/playwright for browser, or dedicated capture service).

---

### Milestone 2: Policy Configuration UI

**Goal:** Users specify what “compliance” means via prompts and structured fields.

| Task | How to Accomplish |
|------|-------------------|
| **Policy schema** | Define JSON schema: `{ rules: [{ type, description, severity }], targets: { person, object, action, environment } }` |
| **Form UI** | Inputs for: target (person/object/action/env), rule description (text), severity (low/med/high/critical), optional regex/keywords. |
| **Preset policies** | Dropdown: "Badge check", "PPE check", "No unauthorized persons", "Area clearance", etc. |
| **Custom prompt field** | Large text area: "Natural language policy" that gets injected into the policy LLM prompt. |
| **State management** | Store policy in React state / Zustand / Redux. Persist to localStorage or backend. |

**Deliverable:** Policy config panel that emits a structured `Policy` object used by downstream models.

**Example Policy object:**
```json
{
  "targets": ["person", "environment"],
  "rules": [
    { "type": "badge", "description": "All persons must wear green badge", "severity": "high" },
    { "type": "presence", "description": "No unauthorized persons in restricted area", "severity": "critical" }
  ],
  "customPrompt": "Focus on safety equipment and access control."
}
```

---

### Milestone 3: VLM Integration — “What do I see?”

**Goal:** Send video frames to a Vision Language Model and get a textual description of the scene.

| Task | How to Accomplish |
|------|-------------------|
| **Choose VLM** | **Primary:** OpenAI GPT-4o / GPT-4 Turbo (vision). **Alternative:** Brev-hosted LLaVA/IDEFICS for cost/quality tradeoff. |
| **Frame selection** | 1 frame every 1–2 seconds (configurable). Max N frames per request to stay under context limits. |
| **Prompt design** | "Describe concisely: people (count, clothing, badges, PPE), objects, actions, environment. Output as structured bullets." |
| **API calls** | OpenAI: `vision` capability with image URLs or base64. Batch frames if model supports multiple images. |
| **Cost control** | Resize images (e.g. 512px), limit frames per run, add rate limiting. |
| **Brev fallback** | If using Brev: same prompt, swap endpoint and payload. Abstract behind `VLMProvider` interface. |

**Deliverable:** Service `analyzeFrames(frames[], policyContext?) -> string` returning structured observations.

**Example VLM output:**
```
- 3 people visible. 2 with green badges, 1 with red badge.
- One person without safety helmet near machinery.
- Bags/backpacks visible near exit.
- Environment: industrial floor, good lighting.
```

---

### Milestone 4: Policy Model — Compliance Decision

**Goal:** LLM takes VLM output + policy and decides compliant / non-compliant with reasoning.

| Task | How to Accomplish |
|------|-------------------|
| **Input assembly** | `{ policy: Policy, observations: string }` |
| **Prompt template** | System: "You are a compliance evaluator." User: "Policy: {policy}. Observations: {observations}. Output: compliant/non-compliant per rule, with brief reasoning." |
| **Output format** | JSON: `{ overall: boolean, verdicts: [{ ruleId, compliant, reason }] }` |
| **Structured output** | Use OpenAI `response_format: { type: "json_schema", schema }` or post-process with regex. |
| **Caching** | Cache policy + observations hash → verdict for repeated runs (optional). |

**Deliverable:** Service `evaluateCompliance(observations, policy) -> ComplianceResult`.

**Example output:**
```json
{
  "overall": false,
  "verdicts": [
    { "ruleId": "badge", "compliant": false, "reason": "1 person with red badge in restricted area" },
    { "ruleId": "ppe", "compliant": false, "reason": "Person without helmet near machinery" }
  ]
}
```

---

### Milestone 5: Report Creation Model — Structured JSON

**Goal:** Turn compliance verdicts into a clean, UI-ready report schema.

| Task | How to Accomplish |
|------|-------------------|
| **Report schema** | Define: `{ summary, incidents[], recommendations[], timestamp, videoId }` |
| **Prompt** | "Given compliance verdicts: {verdicts}. Produce a report with: executive summary, list of incidents (severity, description, timestamp), recommendations." |
| **Output** | Strict JSON schema. Use OpenAI structured output or validate with `zod`/`ajv`. |
| **Idempotency** | Same input → same report (deterministic temperature=0). |

**Deliverable:** Service `createReport(verdicts, metadata) -> Report`.

**Example Report JSON:**
```json
{
  "summary": "2 compliance violations detected. Immediate action required.",
  "incidents": [
    { "severity": "high", "description": "Unauthorized badge color", "timestamp": "00:01:23" },
    { "severity": "critical", "description": "Missing PPE: no helmet", "timestamp": "00:01:23" }
  ],
  "recommendations": ["Verify badge authorization", "Enforce helmet policy"],
  "timestamp": "2026-02-14T12:00:00Z"
}
```

---

### Milestone 6: End-to-End Pipeline API

**Goal:** Single API that orchestrates video → VLM → policy → report.

| Task | How to Accomplish |
|------|-------------------|
| **Orchestration** | `POST /analyze` body: `{ videoSource, policy }`. Flow: 1) extract frames 2) VLM 3) policy eval 4) report. |
| **Async processing** | For long videos, use job queue (Bull/BullMQ, Celery) and poll `GET /job/:id`. |
| **Error handling** | Wrap each step in try/catch. Return partial results + error fields if a step fails. |
| **Idempotency** | Optional: hash(video + policy) → cache full report. |

**Deliverable:** `POST /analyze` returns `{ report, status }` (sync) or `{ jobId }` (async).

---

### Milestone 7: Report Display UI

**Goal:** Show reports in a clear, scannable way.

| Task | How to Accomplish |
|------|-------------------|
| **Report layout** | Summary card, incident list with severity badges, recommendations, timestamps. |
| **Timeline view** | If multiple reports over time (e.g. live monitoring), show timeline with expandable cards. |
| **Severity styling** | Color-code: critical=red, high=orange, medium=yellow, low=green. |
| **Export** | Download as JSON, PDF (react-pdf / jspdf), or CSV. |
| **Live updates** | If using webhooks/SSE for async jobs, show “Processing…” then update when done. |

**Deliverable:** Report view component that consumes `Report` JSON and renders cleanly.

---

### Milestone 8: Whisper Transcript Layer (Future)

**Goal:** Optional audio → transcript → policy/report integration.

| Task | How to Accomplish |
|------|-------------------|
| **Whisper API** | OpenAI Whisper API: `audio` file → transcript. Extract audio from video with ffmpeg. |
| **UI toggle** | "Include transcript analysis" checkbox in policy/config. |
| **Transcript policy** | Define rules: e.g. "No profanity", "Must mention safety briefing", "Keywords: emergency, evacuation". |
| **Policy model extension** | Add transcript to policy LLM input: "Video observations: {...}. Transcript: {...}. Evaluate compliance." |
| **Report extension** | Include transcript-related incidents in report schema. |

**Deliverable:** When toggled, transcript is extracted, sent to policy model, and reflected in report.

---

## Deployment Modes: Cloud vs Local (DGX)

The system supports two deployment modes. **Cloud is the current build target.** Local/DGX is the enterprise upsell — same UI, same pipeline, just different inference backends.

### Cloud Mode (Building Now)

| Component | Provider |
|-----------|----------|
| VLM | OpenAI GPT-4o (vision), Brev-hosted VLMs as alternative |
| Policy LLM | OpenAI GPT-4o / GPT-4o-mini |
| Report LLM | OpenAI GPT-4o-mini |
| Whisper | OpenAI Whisper API |
| Video storage | Temp cloud storage (S3 / local disk), deleted after processing |

- **Pros:** Zero infra, fast to build, easy to demo, scales instantly.
- **Cons:** Data leaves customer premises (deal-breaker for some verticals like defense, healthcare, gov).

### Local Mode — DGX On-Prem (Future)

| Component | Provider |
|-----------|----------|
| VLM | Self-hosted LLaVA / InternVL / Qwen2-VL on DGX (via vLLM or TGI) |
| Policy LLM | Self-hosted Llama 3 / Mixtral on DGX |
| Report LLM | Same local LLM |
| Whisper | Self-hosted Whisper (faster-whisper on GPU) |
| Video storage | On-prem NAS / local disk — never leaves building |

- **Pros:** Full data sovereignty, no API costs at scale, meets compliance for regulated industries.
- **Cons:** Requires DGX hardware, more ops overhead, model quality may lag behind GPT-4o.

### How the Toggle Works (Architecturally)

All model calls go through a **provider abstraction layer**:

```
interface ModelProvider {
  analyzeFrames(frames, prompt) → observations
  evaluatePolicy(observations, policy) → verdicts
  generateReport(verdicts, metadata) → report
  transcribe(audio) → transcript  // future
}

class CloudProvider implements ModelProvider { /* OpenAI SDK calls */ }
class LocalProvider implements ModelProvider { /* vLLM/TGI HTTP calls */ }
```

The UI exposes a "Deployment Mode" setting (or it's set at the org level in a multi-tenant setup). The backend reads the mode and routes to the correct provider. **The pipeline logic is identical in both modes.**

### Why This Matters for Sales

- Start every customer on **Cloud** — zero friction, instant demo.
- When they say "our data can't leave our network" → upgrade to **Local/DGX** (higher contract value, stickier).
- This is a natural **land-and-expand** motion.

---

## Tech Stack Recommendations

| Layer | Recommendation |
|-------|----------------|
| **Frontend** | React + Vite, Tailwind, shadcn/ui or Radix |
| **Backend** | Node.js + Express or Python FastAPI |
| **VLM** | OpenAI GPT-4o (vision) — best UX; Brev for cost if needed |
| **LLM** | OpenAI GPT-4o or GPT-4o-mini for policy + report |
| **Video** | ffmpeg for frame extraction; MediaRecorder for webcam |
| **State** | Zustand or React Query for server state |

---

## Suggested Implementation Order

1. **M0** → Project setup  
2. **M1** → Video input (file first, webcam second)  
3. **M2** → Policy UI  
4. **M3** → VLM integration  
5. **M4** → Policy model  
6. **M5** → Report model  
7. **M6** → Pipeline API  
8. **M7** → Report display  
9. **M8** → Whisper (when ready)  

---

## Cost & Rate Limit Considerations

- **OpenAI:** GPT-4o vision ~$0.01–0.03 per image. Cap frames per run (e.g. 60 frames max = ~$2). Use gpt-4o-mini where possible for text.
- **Brev:** Check pricing for LLaVA/IDEFICS if switching VLMs.
- **Whisper:** ~$0.006/min of audio. Extract only when toggle is on.
- **Rate limits:** Implement retries with exponential backoff; consider queue for burst traffic.

---

## Security & Privacy

- Never log raw video/audio to disk long-term. Use temp files and delete after processing.
- Sanitize policy and report outputs before storing or displaying.
- Use HTTPS; consider signed URLs for video uploads.
- If handling PII, add consent flows and retention policies.

---

## Success Criteria (MVP)

- [ ] Upload video file OR use webcam  
- [ ] Configure policy via UI (targets + rules + custom prompt)  
- [ ] VLM returns observations from video  
- [ ] Policy model returns compliant/non-compliant verdicts  
- [ ] Report model outputs structured JSON  
- [ ] Report displayed cleanly in UI  
- [ ] Export report (JSON at minimum)  

---

*Last updated: Feb 14, 2026*
