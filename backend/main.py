"""FastAPI application entrypoint."""

import logging
import sys

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

# Configure logging BEFORE any application imports.
# logging.basicConfig() is a no-op if the root logger already has handlers
# (e.g. when uvicorn configures logging before importing this module).
# Force our handler onto the root logger so all app modules get proper output.
_root = logging.getLogger()
if not any(isinstance(h, logging.StreamHandler) and h.stream == sys.stderr for h in _root.handlers):
    _handler = logging.StreamHandler(sys.stderr)
    _handler.setFormatter(logging.Formatter("%(asctime)s %(name)s %(levelname)s: %(message)s"))
    _root.addHandler(_handler)
_root.setLevel(logging.INFO)

from backend.core.config import OPENAI_API_KEY
from backend.routers.analyze import router as analyze_router
from backend.routers.polly import router as polly_router

logger = logging.getLogger(__name__)

# Optional async features (require Redis/Celery)
try:
    from backend.routers.async_analyze import router as async_router
    from backend.routers.websocket import router as websocket_router
    ASYNC_ENABLED = True
except ImportError as e:
    logger.warning(f"Async features disabled (Redis/Celery not available): {e}")
    ASYNC_ENABLED = False

app = FastAPI(
    title="Compliance Vision API",
    description="AI-powered video compliance monitoring",
    version="0.1.0",
)

# CORS — allow frontend dev server
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Tighten in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Routers
app.include_router(analyze_router)
app.include_router(polly_router)

# Include async routers if available
if ASYNC_ENABLED:
    app.include_router(async_router)
    app.include_router(websocket_router)
    logger.info("✅ Async features enabled (Celery + WebSocket)")
else:
    logger.info("⚠️ Running without async features (install Redis + run Celery for full functionality)")


@app.get("/health")
async def health_check():
    """Health check endpoint with service status."""
    health_status = {
        "status": "ok",
        "openai_key_set": bool(OPENAI_API_KEY),
    }
    
    # Check Redis connection (if available)
    try:
        from backend.services.celery_app import redis_client
        redis_client.ping()
        health_status["redis"] = "connected"
    except ImportError:
        health_status["redis"] = "not installed"
    except Exception as e:
        health_status["redis"] = f"error: {e}"
        health_status["status"] = "degraded"
    
    # Check Celery workers (if available)
    try:
        from backend.services.celery_app import app as celery_app
        inspect = celery_app.control.inspect()
        stats = inspect.stats()
        health_status["celery_workers"] = len(stats) if stats else 0
    except ImportError:
        health_status["celery_workers"] = "not installed"
    except Exception as e:
        health_status["celery_workers"] = 0
        health_status["celery_error"] = str(e)
    
    # Get API usage stats
    try:
        from backend.services.api_utils import get_usage_stats
        health_status["api_usage"] = get_usage_stats()
    except:
        pass
    
    return health_status
