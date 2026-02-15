"""Celery tasks for async video processing."""

import os
import json
import time
import logging
import asyncio
from typing import Dict, Any
from celery import current_task

from backend.services.celery_app import app, CallbackTask, update_task_progress
from backend.core.config import UPLOAD_DIR, KEYFRAMES_DIR
from backend.models.schemas import Policy, Report, AnalyzeResponse
from backend.services.video import process_video
from backend.services.vlm import analyze_frames
from backend.services.policy import evaluate_and_report, analyze_and_evaluate_combined
from backend.services.whisper import transcribe_video
from backend.services.speech_policy import evaluate_speech

logger = logging.getLogger(__name__)


@app.task(bind=True, base=CallbackTask, name="analyze_video_async")
def analyze_video_async(self, file_path: str, policy_json: str) -> Dict[str, Any]:
    """
    Async video analysis task.
    
    Args:
        file_path: Path to the video file
        policy_json: JSON string of the Policy object
        
    Returns:
        Dictionary with analysis results
    """
    task_id = current_task.request.id
    logger.info(f"Starting async analysis for task {task_id}")
    
    try:
        # Parse policy
        policy = Policy(**json.loads(policy_json))
        update_task_progress(task_id, "parsing", 5, "Policy parsed")
        
        # Stage 1: Frame extraction
        update_task_progress(task_id, "extracting", 10, "Extracting keyframes...")
        video_result = process_video(file_path=file_path, keyframes_dir=KEYFRAMES_DIR)
        
        if not video_result.keyframes:
            raise ValueError("No keyframes extracted from video")
            
        update_task_progress(
            task_id, "extracting", 30, 
            f"Extracted {len(video_result.keyframes)} keyframes"
        )
        
        duration = video_result.metadata.get("duration", 0.0)
        
        # Split rules
        visual_rules = [r for r in policy.rules if r.type != "speech"]
        speech_rules = [r for r in policy.rules if r.type == "speech"]
        has_visual = bool(visual_rules) or bool(policy.custom_prompt)
        has_speech = bool(speech_rules)
        
        # Short video: use combined analysis
        if duration < 15.0 and has_visual and not has_speech:
            update_task_progress(task_id, "analyzing", 50, "Analyzing frames...")
            
            # Run async function in sync context
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                report = loop.run_until_complete(
                    analyze_and_evaluate_combined(
                        keyframes=video_result.keyframes,
                        policy=policy,
                        video_id=video_result.video_id,
                        video_duration=duration,
                        prior_context=policy.prior_context,
                        reference_images=policy.reference_images,
                    )
                )
            finally:
                loop.close()
                
            update_task_progress(task_id, "complete", 100, "Analysis complete")
            
            return {
                "status": "complete",
                "report": report.model_dump(),
                "video_id": video_result.video_id,
                "duration": duration,
                "frames_analyzed": len(video_result.keyframes),
            }
        
        # Long video: multi-stage pipeline
        observations = []
        transcript = None
        
        # Stage 2: VLM + Whisper in parallel
        update_task_progress(task_id, "analyzing", 40, "Analyzing visual content...")
        
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            tasks = []
            if has_visual:
                tasks.append(analyze_frames(video_result.keyframes, policy))
            if has_speech or policy.include_audio:
                tasks.append(transcribe_video(file_path))
                
            if tasks:
                results = loop.run_until_complete(asyncio.gather(*tasks, return_exceptions=True))
                
                if has_visual and not isinstance(results[0], Exception):
                    observations = results[0]
                    
                if (has_speech or policy.include_audio) and len(results) > 1:
                    if not isinstance(results[1], Exception):
                        transcript = results[1]
                        
            update_task_progress(task_id, "evaluating", 70, "Evaluating compliance...")
            
            # Stage 3: Policy evaluation
            if has_visual and observations:
                visual_policy = Policy(
                    rules=visual_rules,
                    custom_prompt=policy.custom_prompt,
                    include_audio=False,
                    reference_images=policy.reference_images,
                )
                report = loop.run_until_complete(
                    evaluate_and_report(
                        observations=observations,
                        policy=visual_policy,
                        video_id=video_result.video_id,
                        video_duration=duration,
                        transcript=transcript,
                        prior_context=policy.prior_context,
                    )
                )
                
                # Add speech verdicts if any
                if has_speech and transcript and transcript.full_text:
                    speech_verdicts = loop.run_until_complete(
                        evaluate_speech(
                            transcript=transcript,
                            speech_rules=speech_rules,
                            custom_prompt=policy.custom_prompt,
                        )
                    )
                    if speech_verdicts:
                        report.all_verdicts.extend(speech_verdicts)
                        speech_incidents = [v for v in speech_verdicts if not v.compliant]
                        report.incidents.extend(speech_incidents)
                        if speech_incidents:
                            report.overall_compliant = False
                            
            else:
                raise ValueError("No observations to evaluate")
                
        finally:
            loop.close()
            
        update_task_progress(task_id, "complete", 100, "Analysis complete")
        
        return {
            "status": "complete",
            "report": report.model_dump(),
            "video_id": video_result.video_id,
            "duration": duration,
            "frames_analyzed": len(observations),
        }
        
    except Exception as e:
        logger.error(f"Task {task_id} failed: {e}", exc_info=True)
        update_task_progress(task_id, "error", 0, str(e))
        raise


@app.task(name="cleanup_old_files")
def cleanup_old_files():
    """Periodic task to clean up old upload and keyframe files."""
    import shutil
    from datetime import datetime, timedelta
    
    cutoff_time = time.time() - (24 * 3600)  # 24 hours ago
    
    for directory in [UPLOAD_DIR, KEYFRAMES_DIR]:
        if not os.path.exists(directory):
            continue
            
        for item in os.listdir(directory):
            item_path = os.path.join(directory, item)
            if os.path.getmtime(item_path) < cutoff_time:
                try:
                    if os.path.isdir(item_path):
                        shutil.rmtree(item_path)
                    else:
                        os.remove(item_path)
                    logger.info(f"Cleaned up old file/directory: {item_path}")
                except Exception as e:
                    logger.error(f"Failed to clean up {item_path}: {e}")