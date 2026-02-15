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


@app.get("/health")
async def health_check():
    return {
        "status": "ok",
        "openai_key_set": bool(OPENAI_API_KEY),
    }
