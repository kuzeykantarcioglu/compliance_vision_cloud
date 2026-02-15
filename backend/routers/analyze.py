"""Analysis router — video upload and full pipeline orchestration.

POST /analyze/upload   → Video → change detection → keyframes (for testing)
POST /analyze/         → Video + Policy → change detection → VLM + Whisper → policy eval → Report
POST /analyze/frame    → Single JPEG frame + Policy → compliance report (real-time webcam)
"""

import os
import json
import time
import uuid
import asyncio
import shutil
import logging

from fastapi import APIRouter, UploadFile, HTTPException, Request, Depends
from starlette.datastructures import FormData

from backend.core.config import UPLOAD_DIR, KEYFRAMES_DIR
from backend.models.schemas import (
    Policy, PolicyRule, AnalyzeResponse, Report, Verdict,
    KeyframeData, FrameAnalyzeRequest, ParallelBatchRequest,
)
from backend.services.video import process_video
from backend.services.vlm import analyze_frames
from backend.services.policy import evaluate_and_report, analyze_and_evaluate_combined
from backend.services.whisper import transcribe_video
from backend.services.speech_policy import evaluate_speech
from backend.services.dgx import analyze_frame_dgx, analyze_frames_dgx_parallel
from backend.services.compliance_state import compliance_tracker

router = APIRouter(prefix="/analyze", tags=["analyze"])
logger = logging.getLogger(__name__)

# Max upload size: 200 MB per part — needed for video uploads
MAX_PART_SIZE = 200 * 1024 * 1024


async def _large_form(request: Request) -> FormData:
    """Parse multipart form with a larger max_part_size (200 MB)."""
    return await request.form(max_part_size=MAX_PART_SIZE)


def _assign_person_thumbnails(report: Report) -> None:
    """Match each PersonSummary to the best frame screenshot.

    Finds the observation closest to first_seen that mentions the person_id
    in its people list, and assigns that frame's image_base64 as the thumbnail.
    """
    if not report.person_summaries or not report.frame_observations:
        return

    for ps in report.person_summaries:
        best_obs = None
        best_dist = float("inf")
        for obs in report.frame_observations:
            if not obs.image_base64:
                continue
            # Check if this person appears in this frame's people list
            person_in_frame = any(
                p.person_id == ps.person_id for p in (obs.people or [])
            )
            if person_in_frame:
                dist = abs(obs.timestamp - ps.first_seen)
                if dist < best_dist:
                    best_dist = dist
                    best_obs = obs
        # Fallback: use observation closest to first_seen even without people match
        if not best_obs:
            for obs in report.frame_observations:
                if obs.image_base64:
                    dist = abs(obs.timestamp - ps.first_seen)
                    if dist < best_dist:
                        best_dist = dist
                        best_obs = obs
        if best_obs:
            ps.thumbnail_base64 = best_obs.image_base64


def _save_upload(video: UploadFile) -> str:
    """Save uploaded video to disk, return file path.

    WebM→MP4 conversion is now handled lazily by process_video() only when
    OpenCV can't read the file directly — saves 1-3s per webcam chunk on
    systems where OpenCV supports WebM natively.
    """
    logger.info(f"📥 Received upload: filename={video.filename}, content_type={video.content_type}")

    os.makedirs(UPLOAD_DIR, exist_ok=True)
    file_path = os.path.join(UPLOAD_DIR, video.filename or "upload.mp4")
    with open(file_path, "wb") as f:
        shutil.copyfileobj(video.file, f)

    file_size_kb = os.path.getsize(file_path) / 1024
    logger.info(f"💾 Saved to disk: {file_path} ({file_size_kb:.1f} KB)")

    return file_path


@router.post("/upload")
async def upload_and_detect(
    form_data: FormData = Depends(_large_form),
):
    """Upload a video file, run change detection, return keyframes.

    First stage of the pipeline — video in, keyframes out.
    Used for testing change detection independently.
    """
    video: UploadFile = form_data["video"]
    if not video.content_type or not video.content_type.startswith("video/"):
        raise HTTPException(status_code=400, detail=f"Expected video, got {video.content_type}")

    file_path = _save_upload(video)

    try:
        result = process_video(file_path=file_path, keyframes_dir=KEYFRAMES_DIR)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Video processing failed: {e}")

    return {
        "video_id": result.video_id,
        "metadata": result.metadata,
        "total_keyframes": len(result.keyframes),
        "keyframes": [
            {
                "timestamp": kf.timestamp,
                "frame_number": kf.frame_number,
                "change_score": kf.change_score,
                "trigger": kf.trigger,
                "image_base64": kf.image_base64[:50] + "..." if kf.image_base64 else "",
            }
            for kf in result.keyframes
        ],
    }


@router.post("/", response_model=AnalyzeResponse)
async def analyze_video(
    form_data: FormData = Depends(_large_form),
):
    """Full pipeline: video + policy → structured compliance report.

    Send as multipart form:
      - video: the video file
      - policy_json: JSON string of the Policy object

    Pipeline stages:
      1. Save video → extract keyframes (change detection)
      2. Send keyframes → GPT-4o vision (VLM observations)
      3. Send observations + policy → GPT-4o-mini (compliance report)

    Each stage is timed and logged.
    """
    logger.info("="*60)
    logger.info("🚀 NEW ANALYSIS REQUEST")
    logger.info("="*60)

    # --- Extract form fields ---
    video: UploadFile = form_data["video"]
    policy_json: str = form_data["policy_json"]

    # --- Parse inputs ---
    try:
        policy = Policy(**json.loads(policy_json))
        logger.info(f"📋 Policy: {len(policy.rules)} rules, custom_prompt={'yes' if policy.custom_prompt else 'no'}, audio={'on' if policy.include_audio else 'off'}")
        for i, rule in enumerate(policy.rules):
            logger.info(f"   Rule {i+1}: [{rule.type}] {rule.severity} — {rule.description[:80]}")
    except Exception as e:
        logger.error(f"❌ Invalid policy JSON: {e}")
        raise HTTPException(status_code=400, detail=f"Invalid policy JSON: {e}")

    if not video.content_type or not video.content_type.startswith("video/"):
        logger.error(f"❌ Bad content type: {video.content_type}")
        raise HTTPException(status_code=400, detail=f"Expected video, got {video.content_type}")

    if not policy.rules and not policy.custom_prompt:
        logger.error("❌ No rules or custom prompt provided")
        raise HTTPException(status_code=400, detail="Policy must have at least one rule or a custom prompt.")

    file_path = _save_upload(video)
    timings = {}

    # --- Stage 1: Frame extraction ---
    logger.info("─"*40)
    logger.info("📹 STAGE 1: Frame Extraction")
    logger.info("─"*40)
    t0 = time.perf_counter()
    try:
        video_result = process_video(file_path=file_path, keyframes_dir=KEYFRAMES_DIR)
    except Exception as e:
        logger.error(f"❌ Stage 1 FAILED: {e}", exc_info=True)
        return AnalyzeResponse(status="error", error=f"[Stage 1: Frame Extraction] {e}")
    timings["frame_extraction"] = round(time.perf_counter() - t0, 2)

    duration = video_result.metadata.get("duration", 0.0)
    logger.info(
        f"✅ Stage 1 done: {len(video_result.keyframes)} keyframes from {duration:.1f}s video in {timings['frame_extraction']}s"
    )
    logger.info(f"   Video metadata: {video_result.metadata}")

    if not video_result.keyframes:
        logger.error(f"❌ No keyframes extracted! Video duration={duration:.1f}s, path={file_path}")
        return AnalyzeResponse(
            status="error",
            error="No keyframes extracted from video. The video may be too short or static.",
        )

    # --- Split rules ---
    visual_rules = [r for r in policy.rules if r.type != "speech"]
    speech_rules = [r for r in policy.rules if r.type == "speech"]
    has_visual = bool(visual_rules) or bool(policy.custom_prompt)
    has_speech = bool(speech_rules)

    logger.info(f"Rules: {len(visual_rules)} visual, {len(speech_rules)} speech | Duration: {duration:.1f}s")

    # --- Short video (webcam chunk): COMBINED single-call pipeline ---
    if duration < 15.0 and has_visual and not has_speech:
        t0 = time.perf_counter()

        # Get effective reference images
        enabled_refs = getattr(policy, "enabled_reference_ids", []) or []
        refs = [r for r in policy.reference_images if getattr(r, "id", None) and r.id in enabled_refs] if enabled_refs else []

        try:
            report = await analyze_and_evaluate_combined(
                keyframes=video_result.keyframes,
                policy=policy,
                video_id=video_result.video_id,
                video_duration=duration,
                prior_context=policy.prior_context,
                reference_images=refs,
            )
        except Exception as e:
            logger.error(f"❌ Combined analysis FAILED: {e}", exc_info=True)
            return AnalyzeResponse(status="error", error=f"[Combined Analysis] {e}")

        timings["combined"] = round(time.perf_counter() - t0, 2)
        _assign_person_thumbnails(report)
        total_time = sum(timings.values())
        logger.info(
            f"Combined pipeline: {total_time:.2f}s total "
            f"(extract={timings['frame_extraction']}s, analyze={timings['combined']}s)"
            f" | {'COMPLIANT' if report.overall_compliant else 'NON-COMPLIANT'}"
            f" | {len(report.person_summaries)} people"
        )
        return AnalyzeResponse(status="complete", report=report)

    # --- Long video (file upload): full multi-stage pipeline ---

    # --- Stage 2: Run VLM + Whisper in parallel ---
    t0 = time.perf_counter()

    concurrent_tasks = {}
    if has_visual:
        concurrent_tasks["vlm"] = analyze_frames(
            keyframes=video_result.keyframes, policy=policy
        )
    if has_speech or policy.include_audio:
        concurrent_tasks["whisper"] = transcribe_video(file_path)

    results = {}
    if concurrent_tasks:
        task_keys = list(concurrent_tasks.keys())
        task_coros = list(concurrent_tasks.values())
        try:
            task_results = await asyncio.gather(*task_coros, return_exceptions=True)
        except Exception as e:
            return AnalyzeResponse(status="error", error=f"[Stage 2] {e}")
        results = dict(zip(task_keys, task_results))

    observations = []
    if "vlm" in results:
        if isinstance(results["vlm"], Exception):
            return AnalyzeResponse(status="error", error=f"[Stage 2: VLM] {results['vlm']}")
        observations = results["vlm"]

    transcript = None
    if "whisper" in results:
        if isinstance(results["whisper"], Exception):
            logger.warning(f"Whisper failed (non-fatal): {results['whisper']}")
        else:
            transcript = results["whisper"]

    timings["stage2_parallel"] = round(time.perf_counter() - t0, 2)
    logger.info(
        f"Stage 2 done: {len(observations)} observations"
        f"{f', transcript: {len(transcript.full_text)} chars' if transcript else ', no audio'}"
        f" in {timings['stage2_parallel']}s"
    )

    # --- Stage 3: Policy evaluation ---
    t0 = time.perf_counter()
    eval_tasks = {}

    if has_visual and observations:
        visual_policy = Policy(
            rules=visual_rules,
            custom_prompt=policy.custom_prompt,
            include_audio=False,
            reference_images=policy.reference_images,
        )
        eval_tasks["visual"] = evaluate_and_report(
            observations=observations,
            policy=visual_policy,
            video_id=video_result.video_id,
            video_duration=duration,
            transcript=transcript,
            prior_context=policy.prior_context,
        )

    if has_speech and (transcript and transcript.full_text or policy.accumulated_transcript):
        eval_tasks["speech"] = evaluate_speech(
            transcript=transcript,
            speech_rules=speech_rules,
            custom_prompt=policy.custom_prompt,
            accumulated_transcript=policy.accumulated_transcript,
        )
    elif has_speech:
        logger.warning("Speech rules present but no audio transcript — skipping speech eval")

    eval_results = {}
    if eval_tasks:
        eval_keys = list(eval_tasks.keys())
        eval_coros = list(eval_tasks.values())
        try:
            eval_outputs = await asyncio.gather(*eval_coros, return_exceptions=True)
        except Exception as e:
            return AnalyzeResponse(status="error", error=f"[Stage 3] {e}")
        eval_results = dict(zip(eval_keys, eval_outputs))

    visual_report = eval_results.get("visual")
    speech_verdicts = eval_results.get("speech", [])

    if isinstance(visual_report, Exception):
        return AnalyzeResponse(status="error", error=f"[Stage 3: Visual Policy] {visual_report}")
    if isinstance(speech_verdicts, Exception):
        logger.warning(f"Speech eval failed: {speech_verdicts}")
        speech_verdicts = []

    if visual_report and speech_verdicts:
        report = visual_report
        report.all_verdicts.extend(speech_verdicts)
        # Only incident-mode speech violations become incidents; checklist-mode are tracked separately
        speech_incidents = [v for v in speech_verdicts if not v.compliant and v.mode == "incident"]
        report.incidents.extend(speech_incidents)
        non_compliant_speech = [v for v in speech_verdicts if not v.compliant]
        if non_compliant_speech:
            report.overall_compliant = False
            report.summary += f" Speech: {len(non_compliant_speech)} audio violation(s)."
        report.transcript = transcript
    elif visual_report:
        report = visual_report
        if has_speech and not speech_verdicts:
            report.summary += " Note: No audio track detected."
            report.transcript = transcript
    elif speech_verdicts:
        from datetime import datetime, timezone
        # Only incident-mode speech violations become incidents
        speech_incidents = [v for v in speech_verdicts if not v.compliant and v.mode == "incident"]
        non_compliant_speech = [v for v in speech_verdicts if not v.compliant]
        report = Report(
            video_id=video_result.video_id,
            summary=f"Speech: {len(non_compliant_speech)} violation(s) of {len(speech_verdicts)} rules.",
            overall_compliant=len(non_compliant_speech) == 0,
            incidents=speech_incidents,
            all_verdicts=speech_verdicts,
            recommendations=[v.reason for v in non_compliant_speech][:3] if non_compliant_speech else ["All speech rules compliant."],
            frame_observations=observations,
            transcript=transcript,
            analyzed_at=datetime.now(timezone.utc).isoformat(),
            total_frames_analyzed=len(observations),
            video_duration=duration,
        )
    else:
        return AnalyzeResponse(status="error", error="No rules to evaluate.")

    timings["policy_evaluation"] = round(time.perf_counter() - t0, 2)

    # Recompute checklist_fulfilled to include speech checklist verdicts
    checklist_verdicts = [v for v in report.all_verdicts if v.mode == "checklist"]
    if checklist_verdicts:
        report.checklist_fulfilled = all(v.compliant for v in checklist_verdicts)

    _assign_person_thumbnails(report)

    total_time = sum(timings.values())
    logger.info(
        f"Pipeline complete: {total_time:.2f}s total "
        f"(extract={timings['frame_extraction']}s, parallel={timings['stage2_parallel']}s, "
        f"eval={timings['policy_evaluation']}s)"
        f" | {len(report.person_summaries)} people tracked"
    )

    return AnalyzeResponse(status="complete", report=report)


# ---------------------------------------------------------------------------
# Real-time frame analysis (webcam snapshot — no video file)
# ---------------------------------------------------------------------------

@router.post("/frame", response_model=AnalyzeResponse)
async def analyze_frame(request: FrameAnalyzeRequest):
    """Real-time frame analysis: single JPEG + policy → compliance report.

    Ultra-fast path for webcam monitoring. No file I/O, no OpenCV, no ffmpeg.
    Sends the frame directly to the combined VLM+policy evaluator.

    Supports two providers:
      - "openai" (default): sends frame to GPT-4o-mini
      - "dgx": sends frame to NVIDIA DGX Spark (Cosmos + Nemotron)
    """
    t0 = time.perf_counter()
    provider = (request.provider or "openai").lower()
    logger.info(f"📸 FRAME ANALYSIS REQUEST (provider={provider})")

    # --- Parse policy ---
    try:
        policy = Policy(**json.loads(request.policy_json))
    except Exception as e:
        logger.error(f"❌ Invalid policy JSON: {e}")
        raise HTTPException(status_code=400, detail=f"Invalid policy JSON: {e}")

    if not policy.rules and not policy.custom_prompt:
        raise HTTPException(status_code=400, detail="Policy must have at least one rule or a custom prompt.")

    # --- Strip data URI prefix if present (canvas.toDataURL includes it) ---
    image_b64 = request.image_base64
    if image_b64.startswith("data:"):
        image_b64 = image_b64.split(",", 1)[1]

    # --- Route to the selected provider ---
    if provider == "dgx":
        # DGX Spark path: send frames to NVIDIA DGX proxy as mp4 video
        # Use batch frames if provided, otherwise single frame fallback
        frames_batch = request.frames if request.frames else None
        try:
            report = await analyze_frame_dgx(
                image_base64=image_b64,
                policy=policy,
                video_id=f"dgx-frame-{uuid.uuid4().hex[:8]}",
                frames=frames_batch,
            )
        except Exception as e:
            logger.error(f"❌ DGX frame analysis FAILED: {e}", exc_info=True)
            return AnalyzeResponse(status="error", error=f"[DGX Frame Analysis] {e}")
    else:
        # OpenAI path (default): send to GPT-4o-mini
        keyframe = KeyframeData(
            timestamp=0.0,
            frame_number=0,
            change_score=1.0,
            trigger="webcam_frame",
            keyframe_path="",
            image_base64=image_b64,
        )

        enabled_refs = policy.enabled_reference_ids or []
        refs = (
            [r for r in policy.reference_images if getattr(r, "id", None) and r.id in enabled_refs]
            if enabled_refs else []
        )

        try:
            report = await analyze_and_evaluate_combined(
                keyframes=[keyframe],
                policy=policy,
                video_id=f"frame-{uuid.uuid4().hex[:8]}",
                video_duration=0.0,
                prior_context=policy.prior_context,
                reference_images=refs,
            )
        except Exception as e:
            logger.error(f"❌ Frame analysis FAILED: {e}", exc_info=True)
            return AnalyzeResponse(status="error", error=f"[Frame Analysis] {e}")

    # --- Evaluate speech rules against accumulated transcript (if provided) ---
    speech_rules = [r for r in policy.rules if r.type == "speech"]
    acc_transcript = request.accumulated_transcript or policy.accumulated_transcript
    if speech_rules and acc_transcript:
        from backend.services.speech_policy import evaluate_speech
        from backend.models.schemas import TranscriptResult
        # Build a minimal TranscriptResult from accumulated text
        dummy_transcript = TranscriptResult(
            full_text="",  # Current chunk has no audio — only accumulated
            segments=[],
            language="en",
            duration=0.0,
        )
        try:
            speech_verdicts = await evaluate_speech(
                transcript=dummy_transcript,
                speech_rules=speech_rules,
                custom_prompt=policy.custom_prompt,
                accumulated_transcript=acc_transcript,
            )
            report.all_verdicts.extend(speech_verdicts)
            speech_incidents = [v for v in speech_verdicts if not v.compliant and v.mode == "incident"]
            report.incidents.extend(speech_incidents)
            if any(not v.compliant for v in speech_verdicts):
                report.overall_compliant = False
        except Exception as e:
            logger.warning(f"Speech evaluation failed (non-fatal): {e}")

        # Recompute checklist_fulfilled
        checklist_verdicts = [v for v in report.all_verdicts if v.mode == "checklist"]
        if checklist_verdicts:
            report.checklist_fulfilled = all(v.compliant for v in checklist_verdicts)

    _assign_person_thumbnails(report)

    elapsed = time.perf_counter() - t0
    logger.info(
        f"📸 Frame analysis ({provider}): {elapsed:.2f}s"
        f" | {'COMPLIANT' if report.overall_compliant else 'NON-COMPLIANT'}"
        f" | {len(report.person_summaries)} people"
        f" | speech_rules={len(speech_rules)}, transcript={len(acc_transcript) if acc_transcript else 0} chars"
    )

    return AnalyzeResponse(status="complete", report=report)

# ---------------------------------------------------------------------------
# Parallel DGX batch analysis — multiple concurrent requests for maximum speed
# ---------------------------------------------------------------------------

@router.post("/frame/parallel", response_model=AnalyzeResponse)
async def analyze_frames_parallel(request: ParallelBatchRequest):
    """Parallel DGX analysis: send multiple frame batches concurrently.

    Accepts multiple batches of JPEG frames and fires them all at the DGX
    Spark proxy simultaneously. Each batch is converted to an mp4 clip
    independently. Results are merged into a single consolidated report.

    This is significantly faster than sequential analysis when the DGX
    proxy can handle concurrent requests.
    """
    t0 = time.perf_counter()
    logger.info(f"🚀 PARALLEL DGX REQUEST: {len(request.batches)} batches, max_concurrent={request.max_concurrent}")

    # Parse policy
    try:
        policy = Policy(**json.loads(request.policy_json))
    except Exception as e:
        logger.error(f"❌ Invalid policy JSON: {e}")
        raise HTTPException(status_code=400, detail=f"Invalid policy JSON: {e}")

    if not policy.rules and not policy.custom_prompt:
        raise HTTPException(status_code=400, detail="Policy must have at least one rule or a custom prompt.")

    if not request.batches:
        raise HTTPException(status_code=400, detail="No frame batches provided.")

    # Flatten all frames from all batches
    all_frames = []
    for batch in request.batches:
        # Strip data URI prefix if present
        cleaned = []
        for frame in batch:
            if frame.startswith("data:"):
                frame = frame.split(",", 1)[1]
            cleaned.append(frame)
        all_frames.extend(cleaned)

    if not all_frames:
        raise HTTPException(status_code=400, detail="All batches are empty.")

    try:
        report = await analyze_frames_dgx_parallel(
            frames=all_frames,
            policy=policy,
            max_concurrent=min(request.max_concurrent, 5),  # cap at 5
            chunk_size=4,  # 4 frames per sub-request (~1s clip each)
        )
    except Exception as e:
        logger.error(f"❌ Parallel DGX analysis FAILED: {e}", exc_info=True)
        return AnalyzeResponse(status="error", error=f"[Parallel DGX Analysis] {e}")

    elapsed = time.perf_counter() - t0
    logger.info(
        f"🏁 Parallel DGX: {elapsed:.2f}s"
        f" | {'COMPLIANT' if report.overall_compliant else 'NON-COMPLIANT'}"
        f" | {len(report.person_summaries)} people"
        f" | {len(request.batches)} batches → {len(all_frames)} total frames"
    )

    return AnalyzeResponse(status="complete", report=report)


# ---------------------------------------------------------------------------
# Audio-only transcription endpoint (for background audio recording)
# ---------------------------------------------------------------------------

@router.post("/transcribe")
async def transcribe_audio_endpoint(
    form_data: FormData = Depends(_large_form),
):
    """Transcribe an audio blob using Whisper. Returns transcript text.

    Lightweight endpoint for background audio recording during webcam monitoring.
    Accepts an audio file (webm/wav/mp3) and returns the transcript.
    """
    t0 = time.perf_counter()
    audio_file: UploadFile = form_data["audio"]
    logger.info(f"🎙️ TRANSCRIBE REQUEST: {audio_file.filename}, {audio_file.content_type}")

    # Save to temp file
    os.makedirs(UPLOAD_DIR, exist_ok=True)
    file_path = os.path.join(UPLOAD_DIR, audio_file.filename or "audio.webm")
    with open(file_path, "wb") as f:
        shutil.copyfileobj(audio_file.file, f)

    try:
        transcript = await transcribe_video(file_path)
    except Exception as e:
        logger.error(f"❌ Transcription failed: {e}", exc_info=True)
        return {"status": "error", "error": str(e), "transcript": None}
    finally:
        if os.path.exists(file_path):
            os.unlink(file_path)

    elapsed = time.perf_counter() - t0

    if transcript and transcript.full_text:
        logger.info(f"🎙️ Transcribed: '{transcript.full_text[:80]}...' in {elapsed:.2f}s")
        return {
            "status": "ok",
            "transcript": {
                "full_text": transcript.full_text,
                "segments": [{"start": s.start, "end": s.end, "text": s.text} for s in transcript.segments],
                "language": transcript.language,
                "duration": transcript.duration,
            },
        }
    else:
        logger.info(f"🎙️ No speech detected in {elapsed:.2f}s")
        return {"status": "ok", "transcript": None}


# ---------------------------------------------------------------------------
# Reset compliance state (for session clear)
# ---------------------------------------------------------------------------

@router.post("/reset")
async def reset_compliance_state():
    """Reset all compliance state. Called when the user clears a monitoring session."""
    compliance_tracker.reset()
    return {"status": "ok"}