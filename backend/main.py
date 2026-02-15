"""FastAPI application entrypoint."""

import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.core.config import OPENAI_API_KEY
from backend.routers.analyze import router as analyze_router
from backend.routers.polly import router as polly_router

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s: %(message)s")

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
