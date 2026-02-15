"""Analysis router — video upload and full pipeline orchestration.

POST /analyze/upload   → Video → change detection → keyframes (for testing)
POST /analyze/         → Video + Policy → change detection → VLM + Whisper → policy eval → Report
"""

import os
import json
import time
import asyncio
import shutil
import logging

from fastapi import APIRouter, UploadFile, File, Form, HTTPException

from backend.core.config import UPLOAD_DIR, KEYFRAMES_DIR
from backend.models.schemas import Policy, PolicyRule, AnalyzeResponse, Report, Verdict
from backend.services.video import process_video
from backend.services.vlm import analyze_frames
from backend.services.policy import evaluate_and_report
from backend.services.whisper import transcribe_video
from backend.services.speech_policy import evaluate_speech

router = APIRouter(prefix="/analyze", tags=["analyze"])
logger = logging.getLogger(__name__)


def _save_upload(video: UploadFile) -> str:
    """Save uploaded video to disk, return file path."""
    os.makedirs(UPLOAD_DIR, exist_ok=True)
    file_path = os.path.join(UPLOAD_DIR, video.filename or "upload.mp4")
    with open(file_path, "wb") as f:
        shutil.copyfileobj(video.file, f)
    return file_path


@router.post("/upload")
async def upload_and_detect(
    video: UploadFile = File(...),
):
    """Upload a video file, run change detection, return keyframes.

    First stage of the pipeline — video in, keyframes out.
    Used for testing change detection independently.
    """
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
    video: UploadFile = File(...),
    policy_json: str = Form(...),
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
    # --- Parse inputs ---
    try:
        policy = Policy(**json.loads(policy_json))
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid policy JSON: {e}")

    if not video.content_type or not video.content_type.startswith("video/"):
        raise HTTPException(status_code=400, detail=f"Expected video, got {video.content_type}")

    if not policy.rules and not policy.custom_prompt:
        raise HTTPException(status_code=400, detail="Policy must have at least one rule or a custom prompt.")

    file_path = _save_upload(video)
    timings = {}

    # --- Stage 1: Change detection ---
    t0 = time.perf_counter()
    try:
        video_result = process_video(file_path=file_path, keyframes_dir=KEYFRAMES_DIR)
    except Exception as e:
        return AnalyzeResponse(status="error", error=f"[Stage 1: Change Detection] {e}")
    timings["change_detection"] = round(time.perf_counter() - t0, 2)

    logger.info(
        f"Stage 1 done: {len(video_result.keyframes)} keyframes in {timings['change_detection']}s"
    )

    if not video_result.keyframes:
        return AnalyzeResponse(
            status="error",
            error="No keyframes extracted from video. The video may be too short or static.",
        )

    # --- Split rules into visual vs speech ---
    visual_rules = [r for r in policy.rules if r.type != "speech"]
    speech_rules = [r for r in policy.rules if r.type == "speech"]
    has_visual = bool(visual_rules) or bool(policy.custom_prompt)
    has_speech = bool(speech_rules) and policy.include_audio

    logger.info(f"Rules: {len(visual_rules)} visual, {len(speech_rules)} speech")

    # --- Stage 2: Run pipelines in parallel ---
    t0 = time.perf_counter()

    concurrent_tasks = {}

    # Visual pipeline: VLM analysis (only if there are visual rules)
    if has_visual:
        concurrent_tasks["vlm"] = analyze_frames(
            keyframes=video_result.keyframes, policy=policy
        )

    # Audio pipeline: Whisper transcription (if speech rules exist or include_audio is on)
    if has_speech or policy.include_audio:
        concurrent_tasks["whisper"] = transcribe_video(file_path)

    # Run all in parallel
    results = {}
    if concurrent_tasks:
        task_keys = list(concurrent_tasks.keys())
        task_coros = list(concurrent_tasks.values())
        try:
            task_results = await asyncio.gather(*task_coros, return_exceptions=True)
        except Exception as e:
            return AnalyzeResponse(status="error", error=f"[Stage 2] {e}")
        results = dict(zip(task_keys, task_results))

    # Extract results, handle failures gracefully
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

    # --- Stage 3: Policy evaluation — visual + speech in parallel ---
    t0 = time.perf_counter()

    eval_tasks = {}

    # Visual policy eval (observations + visual rules → report)
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
            video_duration=video_result.metadata.get("duration", 0.0),
            transcript=transcript,  # Still pass transcript for context
        )

    # Speech policy eval (transcript + speech rules → verdicts)
    if has_speech:
        eval_tasks["speech"] = evaluate_speech(
            transcript=transcript,
            speech_rules=speech_rules,
            custom_prompt=policy.custom_prompt,
        )

    # Run evals in parallel
    eval_results = {}
    if eval_tasks:
        eval_keys = list(eval_tasks.keys())
        eval_coros = list(eval_tasks.values())
        try:
            eval_outputs = await asyncio.gather(*eval_coros, return_exceptions=True)
        except Exception as e:
            return AnalyzeResponse(status="error", error=f"[Stage 3] {e}")
        eval_results = dict(zip(eval_keys, eval_outputs))

    # Build final report by merging visual + speech results
    visual_report = eval_results.get("visual")
    speech_verdicts = eval_results.get("speech", [])

    if isinstance(visual_report, Exception):
        return AnalyzeResponse(status="error", error=f"[Stage 3: Visual Policy] {visual_report}")
    if isinstance(speech_verdicts, Exception):
        logger.warning(f"Speech eval failed: {speech_verdicts}")
        speech_verdicts = []

    # Merge into final report
    if visual_report and speech_verdicts:
        # Merge speech verdicts into the visual report
        report = visual_report
        report.all_verdicts.extend(speech_verdicts)
        speech_incidents = [v for v in speech_verdicts if not v.compliant]
        report.incidents.extend(speech_incidents)
        if speech_incidents:
            report.overall_compliant = False
            report.summary += f" Speech analysis: {len(speech_incidents)} audio violation(s) detected."
        report.transcript = transcript
    elif visual_report:
        report = visual_report
    elif speech_verdicts:
        # Speech-only analysis (no visual rules)
        from datetime import datetime, timezone
        speech_incidents = [v for v in speech_verdicts if not v.compliant]
        report = Report(
            video_id=video_result.video_id,
            summary=f"Speech analysis complete. {len(speech_incidents)} violation(s) out of {len(speech_verdicts)} rules.",
            overall_compliant=len(speech_incidents) == 0,
            incidents=speech_incidents,
            all_verdicts=speech_verdicts,
            recommendations=[v.reason for v in speech_incidents][:3] if speech_incidents else ["All speech rules compliant."],
            frame_observations=observations,
            transcript=transcript,
            analyzed_at=datetime.now(timezone.utc).isoformat(),
            total_frames_analyzed=len(observations),
            video_duration=video_result.metadata.get("duration", 0.0),
        )
    else:
        return AnalyzeResponse(status="error", error="No rules to evaluate.")

    timings["policy_evaluation"] = round(time.perf_counter() - t0, 2)

    logger.info(
        f"Stage 3 done: {'COMPLIANT' if report.overall_compliant else 'NON-COMPLIANT'} "
        f"({len(report.incidents)} incidents) in {timings['policy_evaluation']}s"
    )

    total_time = sum(timings.values())
    logger.info(
        f"Pipeline complete: {total_time:.2f}s total "
        f"(detect={timings['change_detection']}s, parallel={timings['stage2_parallel']}s, "
        f"eval={timings['policy_evaluation']}s)"
    )

    return AnalyzeResponse(status="complete", report=report)
