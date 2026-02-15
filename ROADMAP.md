# Build Roadmap — Step by Step

> Concrete steps from current state to working demo.
> Each step is small enough to build and test before moving on.

---

## What's Done

- [x] **Change detection engine** (`scene_detection.py`)
  - Frame sampling, histogram + structural diff, keyframe extraction
  - Threaded pipeline, streaming webcam support, `on_change` callbacks
  - CLI interface, JSON persistence
- [x] **Steps 1-3: Backend foundation** (`backend/`)
  - FastAPI app, health check, CORS
  - Video upload + change detection service with base64 keyframes
  - Pydantic schemas for full pipeline (Policy → Verdict → Report)
  - Server verified running at `http://127.0.0.1:8000`

---

## Phase 1: Backend Foundation (Steps 1–4)

### Step 1: Project scaffolding

Create the project structure and install dependencies.

```
treehacks2026/
├── backend/
│   ├── main.py              # FastAPI app entrypoint
│   ├── requirements.txt     # Python deps
│   ├── routers/
│   │   └── analyze.py       # /analyze endpoint
│   ├── services/
│   │   ├── video.py         # Video upload + change detection wrapper
│   │   ├── vlm.py           # VLM provider (OpenAI vision calls)
│   │   ├── policy.py        # Policy evaluation LLM
│   │   └── report.py        # Report generation LLM
│   ├── models/
│   │   └── schemas.py       # Pydantic models (Policy, Verdict, Report)
│   └── core/
│       └── config.py        # Settings, env vars, API keys
├── frontend/                # React app (Phase 3)
├── scene_detection.py       # Existing — imported by backend/services/video.py
├── .env                     # OPENAI_API_KEY (gitignored)
├── .env.example
├── .gitignore
├── IMPLEMENTATION_PLAN.md
└── ROADMAP.md
```

**Tasks:**
- [ ] Create `backend/` folder structure
- [ ] Write `requirements.txt`: `fastapi`, `uvicorn`, `python-dotenv`, `openai`, `opencv-python-headless`, `numpy`, `python-multipart`
- [ ] Write `backend/core/config.py`: load `.env`, expose `OPENAI_API_KEY`
- [ ] Write `backend/main.py`: FastAPI app with CORS, health check at `GET /health`
- [ ] Create `.env.example` and `.gitignore`
- [ ] Verify: `uvicorn backend.main:app --reload` starts, `GET /health` returns 200

**Done when:** Server runs and health check responds.

---

### Step 2: Video upload + change detection service

Wire `scene_detection.py` into a FastAPI service.

**Tasks:**
- [ ] Write `backend/services/video.py`:
  - `process_video(file_path) -> dict` that calls `detect_significant_changes()`
  - Returns `{ video_id, metadata, keyframes: [{ timestamp, path, trigger, score }] }`
  - Resizes keyframes to max 512px wide (for VLM cost control)
  - Converts keyframes to base64 for API transport
- [ ] Write `backend/routers/analyze.py`:
  - `POST /analyze/upload` — accepts video file (multipart), saves to temp dir, calls video service
  - Returns change events + base64 keyframes
- [ ] Test: upload a sample video via curl/Postman, verify keyframes are returned

**Done when:** Upload a .mp4, get back a JSON array of keyframes with timestamps and base64 images.

---

### Step 3: Pydantic schemas

Define the data contracts that flow through the pipeline.

**Tasks:**
- [ ] Write `backend/models/schemas.py`:

```python
class PolicyRule(BaseModel):
    type: str                    # "badge", "ppe", "presence", "action", "custom"
    description: str             # "All persons must wear green badge"
    severity: str                # "low" | "medium" | "high" | "critical"

class Policy(BaseModel):
    rules: list[PolicyRule]
    custom_prompt: str = ""      # Free-form natural language additions

class FrameObservation(BaseModel):
    timestamp: float
    description: str             # VLM output for this frame
    trigger: str                 # "change" | "max_gap" | "first" | "last"

class Verdict(BaseModel):
    rule_type: str
    rule_description: str
    compliant: bool
    severity: str
    reason: str
    timestamp: float | None      # When the violation was observed

class Report(BaseModel):
    video_id: str
    summary: str
    overall_compliant: bool
    incidents: list[Verdict]     # Non-compliant verdicts only
    all_verdicts: list[Verdict]  # All verdicts
    recommendations: list[str]
    frame_observations: list[FrameObservation]
    analyzed_at: str             # ISO timestamp
    total_frames_analyzed: int
    video_duration: float

class AnalyzeRequest(BaseModel):
    policy: Policy
    # video comes as multipart file, not in this body

class AnalyzeResponse(BaseModel):
    status: str                  # "complete" | "error"
    report: Report | None
    error: str | None = None
```

**Done when:** Schemas importable, no errors.

---

### Step 4: VLM service — "What do I see?"

Send keyframes to OpenAI GPT-4o and get structured observations.

**Tasks:**
- [ ] Write `backend/services/vlm.py`:
  - `analyze_frames(keyframes: list[dict], policy_context: str) -> list[FrameObservation]`
  - For each keyframe (or batch of keyframes): send base64 image(s) to OpenAI chat completions with `model="gpt-4o"` and image content blocks
  - System prompt: "You are a visual surveillance analyst. Describe what you see concisely: people (count, clothing, badges, PPE, actions), objects, environment state. Be factual and specific."
  - User prompt includes the policy context so VLM knows what to focus on
  - Parse response into `FrameObservation` per keyframe
- [ ] Add image resizing (max 512px width) before base64 encoding to control costs
- [ ] Add batching: send up to 4-5 keyframes per API call (GPT-4o supports multi-image)
- [ ] Test: pass keyframes from step 2 output, verify text descriptions come back

**Done when:** Given keyframe images, returns a list of text observations per frame.

---

## Phase 2: Intelligence Layer (Steps 5–7)

### Step 5: Policy + Report model (single combined call)

One LLM call that takes observations + policy and outputs a full structured report.

> Per earlier feedback: merging policy eval + report generation into one call
> cuts latency ~30% and saves an API round-trip. Use structured output.

**Tasks:**
- [ ] Write `backend/services/policy.py`:
  - `evaluate_and_report(observations: list[FrameObservation], policy: Policy, metadata: dict) -> Report`
  - Single OpenAI call with `model="gpt-4o-mini"` (cheaper, text-only task)
  - Use `response_format: { type: "json_schema", ... }` with the Report schema
  - System prompt: "You are a compliance evaluator. Given video observations and a policy, produce a structured compliance report."
  - User prompt: observations + policy rules + custom prompt
  - Parse into `Report` Pydantic model
- [ ] Add fallback: if structured output parsing fails, retry with stricter prompt
- [ ] Test: pass mock observations + policy, verify Report JSON is valid

**Done when:** Text observations + policy → structured Report JSON.

---

### Step 6: End-to-end pipeline orchestration

Wire steps 2 → 4 → 5 into one API call.

**Tasks:**
- [ ] Update `backend/routers/analyze.py`:
  - `POST /analyze` accepts: video file (multipart) + policy (JSON in form field)
  - Pipeline: upload → change detection → VLM → policy+report → response
  - Wrap in try/except per stage, return partial results on failure
  - Add timing: log how long each stage takes
- [ ] Add `POST /analyze/test` endpoint that uses a hardcoded sample video for quick testing
- [ ] Test: full curl request with video + policy → Report JSON response

**Done when:** Single API call: video file + policy in, Report JSON out.

---

### Step 7: Test with real video

Validate the pipeline end-to-end with a real scenario.

**Tasks:**
- [ ] Record or find a short test video (30-60s) with a visible scene
  (e.g., person walking around a room, pick up an object, etc.)
- [ ] Write a policy: e.g., "All persons must be wearing a badge"
- [ ] Run `POST /analyze`, review the Report JSON
- [ ] Tune parameters:
  - `scene_detection.py` thresholds (are you getting too many / too few keyframes?)
  - VLM prompt (is it describing relevant things?)
  - Policy prompt (are verdicts reasonable?)
- [ ] Save a sample report JSON for frontend development

**Done when:** You have a real Report JSON that makes sense for a real video.

---

## Phase 3: Frontend (Steps 8–11)

### Step 8: React app scaffold

**Tasks:**
- [ ] `npm create vite@latest frontend -- --template react-ts`
- [ ] Install: `tailwindcss`, `@tailwindcss/vite`, `lucide-react` (icons), `axios`
- [ ] Create layout: sidebar nav + main content area
- [ ] Pages/views: `AnalyzePage` (main), `ReportPage` (results)
- [ ] Proxy API requests to backend (`vite.config.ts` proxy or env var)

**Done when:** `npm run dev` shows a styled shell with navigation.

---

### Step 9: Video input + Policy config UI

The main analysis page.

**Tasks:**
- [ ] **Video input section:**
  - File upload dropzone (drag & drop or click)
  - Video preview player (HTML5 `<video>` tag)
  - "Use Webcam" button (stretch — skip for MVP if tight on time)
- [ ] **Policy config section:**
  - "Add Rule" form: type dropdown, description text input, severity selector
  - Rule list with delete buttons
  - Preset policy dropdown: "Badge Check", "PPE Check", "Restricted Area"
  - Custom prompt textarea
- [ ] **Analyze button:** sends video + policy to `POST /analyze`
- [ ] **Loading state:** progress indicator while pipeline runs

**Done when:** Can select video, configure policy, click Analyze, see loading state.

---

### Step 10: Report display

Render the Report JSON in the UI.

**Tasks:**
- [ ] **Summary card:** overall compliant/non-compliant badge, summary text, stats
- [ ] **Incidents list:** cards with severity color coding (critical=red, high=orange, med=yellow, low=green), description, timestamp, reasoning
- [ ] **Observations timeline:** list of frame observations with timestamps, expandable to show VLM descriptions
- [ ] **Recommendations:** bullet list
- [ ] **Export:** "Download JSON" button (later: PDF)

**Done when:** Report JSON renders as a clean, readable dashboard.

---

### Step 11: Polish + demo prep

**Tasks:**
- [ ] Error handling: show user-friendly errors for API failures
- [ ] Loading animations during each pipeline stage
- [ ] Responsive layout (looks good on projector for demo)
- [ ] Create 2-3 demo scenarios with pre-selected videos + policies
- [ ] Test the full flow 3+ times end-to-end
- [ ] Record a backup demo video (in case live demo fails)

**Done when:** You can demo the full flow in under 2 minutes, smoothly.

---

## Phase 4: OpenAI Award Stack (Steps 12–16)

> Goal: maximize OpenAI API surface area with genuine, non-shoehorned uses.
> Core pipeline already uses GPT-4o (vision) + GPT-4o-mini (text) + Structured Outputs.
> These steps add 3 more APIs for a total of **6 OpenAI APIs** in one product.

### Step 12: Whisper — Audio Compliance Layer (~1.5 hours)

Add optional transcript analysis alongside visual analysis.

**Tasks:**
- [ ] Write `backend/services/whisper.py`:
  - `extract_audio(video_path) -> audio_path` — use ffmpeg to extract audio track
  - `transcribe(audio_path) -> TranscriptResult` — call OpenAI Whisper API
  - Return timestamped transcript segments
- [ ] Add `TranscriptSegment` and `TranscriptResult` to schemas
- [ ] Update `backend/services/policy.py`:
  - If transcript is provided, append to policy eval prompt:
    "Video observations: {observations}. Audio transcript: {transcript}. Evaluate compliance."
- [ ] Add transcript-specific policy rules:
  - e.g. "Safety briefing must be delivered before shift start"
  - e.g. "No profanity or hostile language"
  - e.g. "Emergency procedures must be announced"
- [ ] Update Report schema: add `transcript_incidents` and `transcript_text` fields
- [ ] UI: "Include Audio Analysis" toggle checkbox
- [ ] Test: video with speech → transcript appears in report, transcript-based violations detected

**Done when:** Toggle on → audio extracted → transcribed → policy evaluates both video + audio.

**OpenAI API:** `audio.transcriptions.create` (Whisper)

---

### Step 13: Moderation API — Content Safety Flags (~20 minutes)

Flag violent, harmful, or inappropriate content detected in VLM descriptions or transcripts.

**Tasks:**
- [ ] Write `backend/services/moderation.py`:
  - `check_content(text: str) -> ModerationResult`
  - Call `openai.moderations.create(input=text)`
  - Return flagged categories + scores
- [ ] Add `ModerationResult` and `ContentFlag` to schemas
- [ ] Wire into pipeline: run moderation on each VLM observation + transcript
- [ ] Add `content_flags` field to Report — list of flagged content with category + source
- [ ] UI: show content flags as a separate warning section in the report
- [ ] Test: craft an observation/transcript with flaggable content, verify it's caught

**Done when:** Report includes content safety flags from the Moderation API.

**OpenAI API:** `moderations.create`

---

### Step 14: Embeddings — Policy-Observation Relevance Scoring (~30 minutes)

Use embeddings to quantify how relevant each VLM observation is to each policy rule.

**Tasks:**
- [ ] Write `backend/services/embeddings.py`:
  - `compute_relevance(observations: list[str], rules: list[str]) -> list[list[float]]`
  - Embed all observations and rules with `text-embedding-3-small`
  - Compute cosine similarity matrix: observation × rule
  - Return relevance scores (0-1) per observation-rule pair
- [ ] Add `relevance_score` field to Verdict schema
- [ ] Wire into pipeline: after VLM, before policy eval — attach relevance scores
  - Helps the policy LLM focus: "This observation is 0.87 relevant to the badge rule"
  - Also useful in UI: sort/filter observations by relevance to a specific rule
- [ ] Test: verify high-relevance pairs make sense (badge observation ↔ badge rule = high)

**Done when:** Each verdict includes a relevance score. Report shows how closely each observation maps to each rule.

**OpenAI API:** `embeddings.create` (text-embedding-3-small)

---

### Step 15: Webcam Live Input (~2 hours)

Real-time monitoring via browser webcam.

**Tasks:**
- [ ] Frontend: MediaRecorder → capture 10-30s video chunks → POST to `/analyze`
- [ ] Backend: accept chunks, run same pipeline, return incremental reports
- [ ] SSE or polling for live report updates in the UI
- [ ] Use `StreamingDetector` from `scene_detection.py` for server-side webcam (stretch)

**Done when:** Point webcam → see compliance reports updating live.

---

### Step 16: Assistants API — Report Search + Chat (~2 hours, if time)

Query across all past reports conversationally.

**Tasks:**
- [ ] Create an OpenAI Assistant with file_search tool
- [ ] After each analysis, upload the Report JSON as a file to the Assistant's vector store
- [ ] Add chat UI: "Ask about past reports" — e.g. "Which camera had the most PPE violations?"
- [ ] Wire to `/chat` endpoint that forwards to the Assistant

**Done when:** User can chat with their compliance history. "Show me all critical incidents from today."

**OpenAI API:** Assistants API + File Search tool

---

## OpenAI API Coverage Summary

| # | API | Where Used | Status |
|---|-----|-----------|--------|
| 1 | **GPT-4o (vision)** | VLM — frame analysis | Core (Step 4) |
| 2 | **GPT-4o-mini** | Policy eval + report gen | Core (Step 5) |
| 3 | **Structured Outputs** | Report JSON schema enforcement | Core (Step 5) |
| 4 | **Whisper** | Audio transcription for audio compliance | Step 12 |
| 5 | **Moderation** | Content safety flags on observations + transcript | Step 13 |
| 6 | **Embeddings** | Policy-observation relevance scoring | Step 14 |
| 7 | **Assistants + File Search** | Chat across historical reports | Step 16 (stretch) |

---

## Phase 5: Extra Stretch Goals

### Step 17: Multi-camera / multi-video
- Upload multiple videos, get separate reports
- Dashboard view across all feeds

---

## Estimated Time (Hackathon Pace)

| Phase | Steps | Estimated Time |
|-------|-------|---------------|
| Phase 1: Backend foundation | 1–4 | ~3 hours (Steps 1-3 done) |
| Phase 2: Intelligence layer | 5–7 | ~2 hours |
| Phase 3: Frontend | 8–11 | ~4 hours |
| Phase 4: OpenAI award stack | 12–16 | ~6 hours |
| Phase 5: Extra stretch | 17 | ~2+ hours |
| **Total for working demo** | **1–11** | **~6 hours remaining** |
| **Total with OpenAI stack** | **1–16** | **~12 hours remaining** |

---

## Critical Path

The fastest route to a demoable product:

```
Step 1 (scaffold) ──→ Step 2 (video service) ──→ Step 3 (schemas)
                                                        │
Step 4 (VLM) ◄─────────────────────────────────────────┘
      │
Step 5 (policy+report) ──→ Step 6 (pipeline) ──→ Step 7 (test)
                                                        │
Step 8 (React scaffold) ──→ Step 9 (input UI) ──→ Step 10 (report UI)
                                                        │
                                                  Step 11 (polish)
```

Steps 1-3: DONE.
Steps 4-5 are the core intelligence — get these right.
Steps 8-10 frontend can be parallelized if you have a teammate.
Steps 12-14 (Whisper, Moderation, Embeddings) are quick wins — do after core pipeline works.

---

## Priority Order (what to build next)

```
NOW:    Step 4 (VLM) → Step 5 (policy+report) → Step 6 (wire pipeline) → Step 7 (test)
THEN:   Step 8-11 (frontend)
AWARDS: Step 12 (Whisper) → Step 13 (Moderation) → Step 14 (Embeddings)
BONUS:  Step 15 (webcam live) → Step 16 (Assistants chat)
```

*Last updated: Feb 14, 2026*
