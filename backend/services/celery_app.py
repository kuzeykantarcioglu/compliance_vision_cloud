"""Celery configuration and task definitions for async video processing."""

import os
import json
import logging
from typing import Dict, Any
from celery import Celery, Task
from celery.result import AsyncResult
import redis
import asyncio

# Configure Celery
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")

app = Celery(
    "compliance_vision",
    broker=REDIS_URL,
    backend=REDIS_URL,
    include=["backend.services.celery_tasks"]
)

# Celery configuration
app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    result_expires=3600,  # Results expire after 1 hour
    task_track_started=True,
    task_time_limit=300,  # 5 minute hard limit per task
    task_soft_time_limit=240,  # 4 minute soft limit
    worker_prefetch_multiplier=1,  # Process one task at a time
    worker_max_tasks_per_child=50,  # Restart worker after 50 tasks to prevent memory leaks
)

# Redis client for real-time updates
redis_client = redis.from_url(REDIS_URL, decode_responses=True)

logger = logging.getLogger(__name__)


class CallbackTask(Task):
    """Base task with callbacks for progress updates."""
    
    def on_success(self, retval, task_id, args, kwargs):
        """Called on successful task completion."""
        logger.info(f"Task {task_id} completed successfully")
        # Store completion status in Redis
        redis_client.setex(f"task:{task_id}:status", 3600, "complete")
        
    def on_failure(self, exc, task_id, args, kwargs, einfo):
        """Called on task failure."""
        logger.error(f"Task {task_id} failed: {exc}")
        # Store error in Redis
        redis_client.setex(f"task:{task_id}:status", 3600, "failed")
        redis_client.setex(f"task:{task_id}:error", 3600, str(exc))


def update_task_progress(task_id: str, stage: str, progress: int, message: str = ""):
    """Update task progress in Redis for real-time monitoring."""
    data = {
        "stage": stage,
        "progress": progress,
        "message": message,
    }
    redis_client.setex(f"task:{task_id}:progress", 300, json.dumps(data))
    redis_client.publish(f"task:{task_id}:updates", json.dumps(data))


def get_task_status(task_id: str) -> Dict[str, Any]:
    """Get current task status from Celery and Redis."""
    result = AsyncResult(task_id, app=app)
    
    # Get progress from Redis
    progress_data = redis_client.get(f"task:{task_id}:progress")
    progress = json.loads(progress_data) if progress_data else {}
    
    # Get error if any
    error = redis_client.get(f"task:{task_id}:error")
    
    status = {
        "task_id": task_id,
        "state": result.state,
        "ready": result.ready(),
        "successful": result.successful() if result.ready() else None,
        "progress": progress,
        "error": error,
    }
    
    if result.ready() and result.successful():
        status["result"] = result.result
        
    return status


def cancel_task(task_id: str) -> bool:
    """Cancel a running task."""
    result = AsyncResult(task_id, app=app)
    result.revoke(terminate=True)
    redis_client.setex(f"task:{task_id}:status", 3600, "cancelled")
    return True