"""WebSocket endpoints for real-time updates."""

import json
import asyncio
import logging
from typing import Dict, Set
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
import redis.asyncio as aioredis

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/ws", tags=["websocket"])

# Track active connections
active_connections: Dict[str, Set[WebSocket]] = {}


class ConnectionManager:
    """Manages WebSocket connections for real-time updates."""
    
    def __init__(self):
        self.active_connections: Dict[str, Set[WebSocket]] = {}
        self.redis_client = None
        self.pubsub = None
        
    async def connect(self, websocket: WebSocket, task_id: str):
        """Accept a new WebSocket connection for a task."""
        await websocket.accept()
        
        if task_id not in self.active_connections:
            self.active_connections[task_id] = set()
        self.active_connections[task_id].add(websocket)
        
        logger.info(f"WebSocket connected for task {task_id}")
        
        # Send initial status
        try:
            from backend.services.celery_app import get_task_status
            status = get_task_status(task_id)
            await websocket.send_json(status)
        except Exception as e:
            logger.error(f"Failed to send initial status: {e}")
    
    def disconnect(self, websocket: WebSocket, task_id: str):
        """Remove a WebSocket connection."""
        if task_id in self.active_connections:
            self.active_connections[task_id].discard(websocket)
            if not self.active_connections[task_id]:
                del self.active_connections[task_id]
        logger.info(f"WebSocket disconnected for task {task_id}")
    
    async def send_update(self, task_id: str, data: dict):
        """Send an update to all connections watching a task."""
        if task_id in self.active_connections:
            disconnected = set()
            for websocket in self.active_connections[task_id]:
                try:
                    await websocket.send_json(data)
                except Exception as e:
                    logger.warning(f"Failed to send update: {e}")
                    disconnected.add(websocket)
            
            # Clean up disconnected sockets
            for ws in disconnected:
                self.active_connections[task_id].discard(ws)
    
    async def subscribe_to_updates(self, task_id: str):
        """Subscribe to Redis pub/sub for task updates."""
        try:
            redis = aioredis.from_url("redis://localhost:6379", decode_responses=True)
            pubsub = redis.pubsub()
            await pubsub.subscribe(f"task:{task_id}:updates")
            
            async for message in pubsub.listen():
                if message["type"] == "message":
                    try:
                        data = json.loads(message["data"])
                        await self.send_update(task_id, data)
                    except json.JSONDecodeError:
                        logger.warning(f"Invalid JSON in Redis message: {message['data']}")
                        
        except Exception as e:
            logger.error(f"Redis subscription error: {e}")
        finally:
            if pubsub:
                await pubsub.close()


manager = ConnectionManager()


@router.websocket("/task/{task_id}")
async def websocket_endpoint(websocket: WebSocket, task_id: str):
    """
    WebSocket endpoint for real-time task updates.
    
    Connect to this endpoint to receive live updates about a task's progress.
    Updates are pushed whenever the task status changes.
    """
    await manager.connect(websocket, task_id)
    
    # Start Redis subscription in background
    subscription_task = asyncio.create_task(manager.subscribe_to_updates(task_id))
    
    try:
        # Keep connection alive and handle incoming messages
        while True:
            # We don't expect client to send messages, but need to keep reading
            # to detect disconnection
            try:
                data = await asyncio.wait_for(websocket.receive_text(), timeout=30.0)
                # Echo back any received messages (for ping/pong)
                if data == "ping":
                    await websocket.send_text("pong")
            except asyncio.TimeoutError:
                # Send periodic status updates
                try:
                    from backend.services.celery_app import get_task_status
                    status = get_task_status(task_id)
                    await websocket.send_json(status)
                    
                    # If task is complete, close connection after sending final status
                    if status.get("ready", False):
                        await asyncio.sleep(1)  # Give client time to process
                        break
                except Exception as e:
                    logger.error(f"Failed to send status update: {e}")
                    
    except WebSocketDisconnect:
        logger.info(f"Client disconnected from task {task_id}")
    except Exception as e:
        logger.error(f"WebSocket error: {e}")
    finally:
        manager.disconnect(websocket, task_id)
        subscription_task.cancel()
        
        
@router.websocket("/monitor")
async def monitor_endpoint(websocket: WebSocket):
    """
    WebSocket endpoint for monitoring all tasks.
    
    Useful for admin dashboards to monitor overall system activity.
    """
    await websocket.accept()
    logger.info("Monitor WebSocket connected")
    
    try:
        while True:
            # Send queue stats every 5 seconds
            try:
                from backend.services.celery_app import app
                from backend.services.api_utils import get_usage_stats
                
                inspect = app.control.inspect()
                
                stats = {
                    "type": "queue_stats",
                    "active_tasks": len(inspect.active() or {}),
                    "scheduled_tasks": len(inspect.scheduled() or {}),
                    "api_usage": get_usage_stats(),
                    "timestamp": asyncio.get_event_loop().time(),
                }
                
                await websocket.send_json(stats)
                await asyncio.sleep(5)
                
            except Exception as e:
                logger.error(f"Failed to send monitor update: {e}")
                await asyncio.sleep(5)
                
    except WebSocketDisconnect:
        logger.info("Monitor WebSocket disconnected")
    except Exception as e:
        logger.error(f"Monitor WebSocket error: {e}")