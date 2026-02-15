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

from fastapi import APIRouter, UploadFile, HTTPException, Request, Depends
from starlette.datastructures import FormData

from backend.core.config import UPLOAD_DIR, KEYFRAMES_DIR
from backend.models.schemas import Policy, PolicyRule, AnalyzeResponse, Report, Verdict
from backend.services.video import process_video
from backend.services.vlm import analyze_frames
from backend.services.policy import evaluate_and_report, analyze_and_evaluate_combined
from backend.services.whisper import transcribe_video
from backend.services.speech_policy import evaluate_speech

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
    """Save uploaded video to disk, return file path."""
    os.makedirs(UPLOAD_DIR, exist_ok=True)
    file_path = os.path.join(UPLOAD_DIR, video.filename or "upload.mp4")
    with open(file_path, "wb") as f:
        shutil.copyfileobj(video.file, f)
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
    # --- Extract form fields ---
    video: UploadFile = form_data["video"]
    policy_json: str = form_data["policy_json"]

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

    # --- Stage 1: Frame extraction ---
    t0 = time.perf_counter()
    try:
        video_result = process_video(file_path=file_path, keyframes_dir=KEYFRAMES_DIR)
    except Exception as e:
        return AnalyzeResponse(status="error", error=f"[Stage 1: Frame Extraction] {e}")
    timings["frame_extraction"] = round(time.perf_counter() - t0, 2)

    duration = video_result.metadata.get("duration", 0.0)
    logger.info(
        f"Stage 1 done: {len(video_result.keyframes)} keyframes in {timings['frame_extraction']}s"
    )

    if not video_result.keyframes:
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

    if has_speech and transcript and transcript.full_text:
        eval_tasks["speech"] = evaluate_speech(
            transcript=transcript,
            speech_rules=speech_rules,
            custom_prompt=policy.custom_prompt,
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
        speech_incidents = [v for v in speech_verdicts if not v.compliant]
        report.incidents.extend(speech_incidents)
        if speech_incidents:
            report.overall_compliant = False
            report.summary += f" Speech: {len(speech_incidents)} audio violation(s)."
        report.transcript = transcript
    elif visual_report:
        report = visual_report
        if has_speech and not speech_verdicts:
            report.summary += " Note: No audio track detected."
            report.transcript = transcript
    elif speech_verdicts:
        from datetime import datetime, timezone
        speech_incidents = [v for v in speech_verdicts if not v.compliant]
        report = Report(
            video_id=video_result.video_id,
            summary=f"Speech: {len(speech_incidents)} violation(s) of {len(speech_verdicts)} rules.",
            overall_compliant=len(speech_incidents) == 0,
            incidents=speech_incidents,
            all_verdicts=speech_verdicts,
            recommendations=[v.reason for v in speech_incidents][:3] if speech_incidents else ["All speech rules compliant."],
            frame_observations=observations,
            transcript=transcript,
            analyzed_at=datetime.now(timezone.utc).isoformat(),
            total_frames_analyzed=len(observations),
            video_duration=duration,
        )
    else:
        return AnalyzeResponse(status="error", error="No rules to evaluate.")

    timings["policy_evaluation"] = round(time.perf_counter() - t0, 2)

    _assign_person_thumbnails(report)

    total_time = sum(timings.values())
    logger.info(
        f"Pipeline complete: {total_time:.2f}s total "
        f"(extract={timings['frame_extraction']}s, parallel={timings['stage2_parallel']}s, "
        f"eval={timings['policy_evaluation']}s)"
        f" | {len(report.person_summaries)} people tracked"
    )

    return AnalyzeResponse(status="complete", report=report)
