import os
from dotenv import load_dotenv

# Load .env from project root (one level up from backend/)
load_dotenv(os.path.join(os.path.dirname(__file__), "..", "..", ".env"))

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
UPLOAD_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "uploads")
KEYFRAMES_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "keyframes")

# Ensure directories exist
os.makedirs(UPLOAD_DIR, exist_ok=True)
os.makedirs(KEYFRAMES_DIR, exist_ok=True)
