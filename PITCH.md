# Compliance Vision — AI Video Compliance Monitoring

> **One-liner:** Define any compliance policy in plain English. Point it at any camera. Get structured, audit-ready reports automatically.

---

## The Problem

Physical security and compliance monitoring is a **$130B+ market** running on human eyeballs.

- **Security guards** watch camera feeds for 8+ hours. Studies show attention drops to ~20% effectiveness after 20 minutes of continuous monitoring.
- **Compliance audits** are manual, infrequent (quarterly/annual), and retrospective. Violations happen between audits.
- **Incident reports** are written by hand, inconsistent, and not machine-readable. They can't feed dashboards, insurance claims, or legal processes without manual re-entry.
- **Every new compliance rule** (new PPE requirement, new badge policy, new restricted zone) requires retraining staff, updating procedures, and hoping humans remember.

Existing video analytics solutions (Verkada, Rhombus, Ambient.ai) hardcode detections: "person detected," "motion detected," "vehicle detected." If your compliance rule doesn't match their pre-built model, you're out of luck. Custom CV model training takes months and six-figure budgets.

---

## The Solution

**Compliance Vision** lets any organization define compliance policies in natural language and apply them to any video source — file uploads or live camera feeds — with AI that sees, evaluates, and reports in real-time.

```
"All personnel in Zone 3 must wear a hard hat and yellow safety vest"
     ↓
  AI watches the camera feed
     ↓
  Structured report: 2 violations detected, timestamps, severity, recommendations
```

No model training. No computer vision expertise. No six-month integration project. Write the rule, point the camera, get the report.

---

## How It Works — The Pipeline

| Stage | What happens | Technical detail |
|-------|-------------|-----------------|
| **1. Ingest** | Video file uploaded or live webcam connected | Supports any video format, RTSP streams, webcam |
| **2. Smart sampling** | Intelligent change detection extracts only the frames that matter | Dual-metric engine (histogram + structural diff) with threaded pipeline. Skips static footage, catches meaningful changes. Reduces frames sent to AI by 80-95%. |
| **3. Vision analysis** | Each keyframe is described by a Vision Language Model | GPT-4o (cloud) or self-hosted VLM (on-prem). "What do I see?" — people, objects, actions, environment. |
| **4. Policy evaluation** | An LLM evaluates the visual observations against the customer's policy | Structured input: observations + policy rules. Structured output: per-rule compliant/non-compliant verdicts with reasoning. |
| **5. Report generation** | A structured, audit-ready JSON report is produced | Executive summary, incident list with severity + timestamps, actionable recommendations. |
| **6. Display + export** | Reports rendered in a clean UI and exportable | Severity-coded incident cards, timeline view, JSON/PDF export. |

**Future: Audio layer** — Whisper transcription adds spoken-word compliance (safety briefings, verbal announcements, hostile language detection). Toggle on/off per feed.

---

## Selling Points

### 1. Policy-as-Prompt: Any Rule, No Training

Traditional video analytics require training a custom CV model for each new detection type. That's months of data collection, labeling, training, and validation.

We use foundation models (VLMs + LLMs). The "model" is the prompt. Want to check for hard hats? Type it. Want to check that the fire exit is unobstructed? Type it. Want to verify that exactly 2 guards are present at the gate between 10pm-6am? Type it.

**Time to deploy a new compliance rule: minutes, not months.**

### 2. Cloud-to-Local: Land and Expand

Two deployment modes, same product:

| | Cloud | Local (DGX On-Prem) |
|---|---|---|
| **Inference** | OpenAI GPT-4o | Self-hosted VLM + LLM on DGX |
| **Data residency** | Cloud | Never leaves the building |
| **Setup time** | Minutes | Days (one-time) |
| **Best for** | SMBs, fast pilots, demos | Defense, healthcare, gov, regulated industries |
| **Contract value** | $$ | $$$$ |

**GTM motion:** Start every customer on Cloud (zero friction, instant demo). When they say "our video data can't leave our network" — upgrade to Local. Higher ACV, stickier deployment, longer contracts.

### 3. Smart Frame Sampling — 80-95% Cost Reduction

Naive approach: send every frame (30 FPS) to the VLM. That's 1,800 API calls per minute per camera. Unusable.

Our change detection engine analyzes frames locally (zero API cost) and only sends keyframes where something visually significant changed. A typical security camera with occasional activity produces 2-5 keyframes per minute instead of 1,800 frames per minute.

**This isn't just a cost optimization — it's what makes the product economically viable at scale.**

Technical depth:
- Dual-metric scoring: HSV histogram correlation (catches global changes like lighting) + structural pixel diff (catches local changes like a person entering)
- Early termination: if the cheap histogram check says "nothing changed" (correlation > 0.95), the expensive structural diff is skipped entirely — saves ~50% compute on static frames
- Threaded pipeline: frame reading, change detection, and keyframe writing run in parallel threads. OpenCV releases the GIL, so threads get true CPU parallelism
- Adaptive debouncing: configurable min interval between captures prevents burst detections from camera jitter

### 4. Real-Time Streaming Architecture

Not just batch processing. The system supports live webcam and RTSP feeds with a purpose-built streaming architecture:

- **Ring buffer capture**: a grabber thread continuously reads the camera and stores only the latest frame. If processing is slower than capture, intermediate frames are dropped — no memory buildup, no queue explosion.
- **Event-driven VLM calls**: an `on_change` callback fires immediately when a significant change is detected. The VLM starts analyzing the first event while the camera keeps running. No "wait for the video to finish" bottleneck.
- **Designed for multi-camera**: each `StreamingDetector` is self-contained with its own threads. Run N detectors for N cameras, each independently streaming events to the VLM.

### 5. Structured, Audit-Ready Output

Every report is a machine-readable JSON document with a defined schema:

```json
{
  "summary": "2 compliance violations detected in Zone 3.",
  "overall_compliant": false,
  "incidents": [
    {
      "severity": "critical",
      "description": "Person without hard hat near active machinery",
      "timestamp": "00:01:23",
      "rule": "All personnel must wear hard hats",
      "reason": "VLM observed person near CNC machine without head protection"
    }
  ],
  "recommendations": ["Enforce hard hat policy at Zone 3 entry", "Install signage"],
  "analyzed_at": "2026-02-14T12:00:00Z"
}
```

This means reports can feed directly into:
- Compliance dashboards and BI tools
- Insurance claim systems
- Incident ticketing (Jira, ServiceNow)
- Legal/regulatory audit trails
- Automated alerting (Slack, PagerDuty, email)

No human needs to re-type anything. The report is the source of truth.

### 6. Audio + Video Fusion (Upcoming)

When the Whisper layer is enabled, the system analyzes both what it **sees** and what it **hears**:

- Was the safety briefing delivered before shift start?
- Were emergency evacuation instructions announced?
- Is there verbal aggression or harassment?
- Are required verbal confirmations being made? ("Clear!" / "Fire in the hole!")

**No competitor in the visual compliance space does audio.** This is a unique wedge.

---

## Technical Complexities We've Solved (or are Solving)

### Already Built

| Challenge | Our approach |
|-----------|-------------|
| **Redundant frame processing at scale** | Dual-metric change detection (histogram + structural diff) that reduces frames by 80-95% before any API call |
| **Seeking performance in compressed video** | Sequential `cap.read()` with frame counting instead of `cap.set(POS_FRAMES)` — 5-10x faster on H.264/H.265 |
| **Detection blocking on disk I/O** | Threaded `KeyframeWriter` queues writes to background — detection loop never waits on disk |
| **I/O vs compute overlap** | Threaded reader pipeline: one thread decodes video, another runs change detection — true parallelism via GIL release |
| **Real-time memory management** | Ring buffer (size 1) for live feeds — always latest frame, no queue buildup regardless of processing speed |
| **Noise/jitter in camera feeds** | Min-interval debouncing + Gaussian blur preprocessing + configurable sensitivity thresholds |
| **Static scene coverage** | Max-gap parameter forces periodic keyframes even when nothing changes, so VLM never has blind spots |

### Solving Next

| Challenge | Approach |
|-----------|---------|
| **VLM cost at scale (50+ cameras)** | Aggressive frame dedup, batch multi-image requests, gpt-4o-mini for text tasks, eventual local VLM on DGX |
| **Latency for real-time alerting** | Event-driven `on_change` callbacks pipeline keyframes to VLM immediately, not batch-after-video |
| **Structured output reliability** | OpenAI JSON schema mode + Pydantic validation + retry with stricter prompt on parse failure |
| **Multi-modal policy evaluation** | Merging video observations + audio transcript into a single policy evaluation context |
| **On-prem deployment without cloud deps** | Provider abstraction layer: `CloudProvider` (OpenAI SDK) vs `LocalProvider` (vLLM/TGI HTTP) — same pipeline, swappable backend |

---

## Market Opportunity

### Who Buys This

| Segment | Use case | Why they pay |
|---------|----------|-------------|
| **Manufacturing / Industrial** | PPE compliance, restricted zone monitoring, safety protocol verification | OSHA fines: $16,131 per violation, $161,323 for willful. Prevention is cheaper. |
| **Construction** | Hard hat, vest, harness checks across dynamic job sites | Insurance premiums tied to safety record. Documented compliance = lower premiums. |
| **Healthcare** | Badge verification, restricted area access, hygiene compliance | HIPAA, JCAHO — non-compliance risks facility accreditation. |
| **Defense / Government** | Perimeter monitoring, personnel verification, classified area access | Require on-prem (DGX mode). Highest ACV segment. |
| **Retail / Logistics** | Theft prevention, operational compliance, warehouse safety | Shrinkage costs US retailers ~$100B/year. |
| **Property Management** | Building security, tenant compliance, incident documentation | Liability reduction, insurance requirements. |

### Pricing Model (Projected)

| Tier | Target | Price |
|------|--------|-------|
| **Cloud Starter** | SMBs, 1-5 cameras | $200-500/mo |
| **Cloud Pro** | Mid-market, 5-50 cameras, custom policies | $1,000-5,000/mo |
| **Enterprise On-Prem** | Regulated industries, DGX deployment | $50,000-200,000/yr |

---

## Competitive Landscape

| Company | What they do | Our advantage |
|---------|-------------|---------------|
| **Verkada** | Camera hardware + cloud analytics | Hardcoded detections only. No custom policy. No audio. |
| **Rhombus** | Cloud cameras + AI alerts | Same: fixed detection types. Can't define "everyone needs a green badge." |
| **Ambient.ai** | Threat detection for physical security | Focused on threats (guns, fights). Not general compliance. No policy-as-prompt. |
| **Voxel AI** | Workplace safety AI | Closer competitor. But pre-built safety models, not user-defined policies. No audio layer. |
| **Spot AI** | Camera analytics + search | Retrospective search, not proactive compliance monitoring. |

**Our moat:** Policy-as-prompt flexibility (any rule, not just pre-trained detections) + audio-visual fusion + cloud-to-local deployment option. Three things no competitor offers together.

---

## Team Requirements (for YC Application)

What you'd need to scale this:
- **ML/Infra engineer**: Optimize VLM inference, build the DGX local deployment, fine-tune open-source VLMs on compliance-specific data
- **Full-stack engineer**: Production UI, multi-tenant backend, camera integrations (ONVIF/RTSP)
- **Go-to-market**: Pilot partnerships with 2-3 manufacturing/construction companies for design partners

---

## Current Status

| Component | Status |
|-----------|--------|
| Change detection engine (threaded, real-time capable) | Built |
| Streaming webcam support | Built |
| Architecture + pipeline design | Designed |
| Backend API (FastAPI) | Next |
| VLM integration (OpenAI GPT-4o) | Next |
| Policy evaluation + report generation | Next |
| Frontend UI | Next |
| Whisper audio layer | Planned |
| DGX on-prem mode | Planned |

---

*Feb 14, 2026 — TreeHacks*
