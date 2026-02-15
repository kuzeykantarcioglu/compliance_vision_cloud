"""Async analysis router with Celery task queue."""

import os
import json
import uuid
import shutil
import logging
from typing import Optional

from fastapi import APIRouter, UploadFile, HTTPException, BackgroundTasks
from fastapi.responses import JSONResponse

from backend.core.config import UPLOAD_DIR
from backend.models.schemas import Policy
from backend.services.celery_app import get_task_status, cancel_task
from backend.services.celery_tasks import analyze_video_async

router = APIRouter(prefix="/async", tags=["async"])
logger = logging.getLogger(__name__)


@router.post("/analyze")
async def start_async_analysis(
    video: UploadFile,
    policy_json: str,
):
    """
    Start async video analysis. Returns immediately with a task ID.
    
    Returns:
        task_id: Use this to check status via GET /async/status/{task_id}
    """
    logger.info(f"📥 Starting async analysis: {video.filename}")
    
    # Parse and validate policy
    try:
        policy = Policy(**json.loads(policy_json))
        if not policy.rules and not policy.custom_prompt:
            raise ValueError("Policy must have at least one rule or custom prompt")
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid policy: {e}")
    
    # Validate video
    if not video.content_type or not video.content_type.startswith("video/"):
        raise HTTPException(status_code=400, detail=f"Expected video, got {video.content_type}")
    
    # Save video to disk
    os.makedirs(UPLOAD_DIR, exist_ok=True)
    file_id = f"{uuid.uuid4().hex[:12]}_{video.filename}"
    file_path = os.path.join(UPLOAD_DIR, file_id)
    
    try:
        with open(file_path, "wb") as f:
            shutil.copyfileobj(video.file, f)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to save video: {e}")
    
    # Queue the task
    task = analyze_video_async.delay(file_path, policy_json)
    
    logger.info(f"✅ Queued task {task.id} for {video.filename}")
    
    return JSONResponse(
        status_code=202,  # Accepted
        content={
            "task_id": task.id,
            "status": "queued",
            "message": "Analysis started. Check status endpoint for updates.",
            "status_url": f"/async/status/{task.id}",
        }
    )


@router.get("/status/{task_id}")
async def get_analysis_status(task_id: str):
    """
    Check the status of an async analysis task.
    
    Returns task status, progress, and results when complete.
    """
    try:
        status = get_task_status(task_id)
        
        # Add user-friendly state descriptions
        state_messages = {
            "PENDING": "Task is waiting in queue",
            "STARTED": "Task has started processing",
            "SUCCESS": "Task completed successfully",
            "FAILURE": "Task failed",
            "RETRY": "Task is being retried",
            "REVOKED": "Task was cancelled",
        }
        
        status["message"] = state_messages.get(status["state"], "Processing")
        
        return status
        
    except Exception as e:
        logger.error(f"Failed to get status for task {task_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to get task status: {e}")


@router.delete("/cancel/{task_id}")
async def cancel_analysis(task_id: str):
    """Cancel a running analysis task."""
    try:
        success = cancel_task(task_id)
        if success:
            return {"message": f"Task {task_id} cancelled", "success": True}
        else:
            return {"message": f"Failed to cancel task {task_id}", "success": False}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to cancel task: {e}")


@router.get("/queue/stats")
async def get_queue_stats():
    """Get current queue statistics."""
    try:
        from backend.services.celery_app import app
        
        # Get queue info
        inspect = app.control.inspect()
        
        stats = {
            "active": len(inspect.active() or {}),
            "scheduled": len(inspect.scheduled() or {}),
            "reserved": len(inspect.reserved() or {}),
        }
        
        # Get worker status
        ping_responses = app.control.ping(timeout=1.0)
        stats["workers_online"] = len(ping_responses) if ping_responses else 0
        
        return stats
        
    except Exception as e:
        logger.error(f"Failed to get queue stats: {e}")
        return {
            "active": 0,
            "scheduled": 0,
            "reserved": 0,
            "workers_online": 0,
            "error": str(e),
        }