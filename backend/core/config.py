import os
from dotenv import load_dotenv
from openai import AsyncOpenAI

# Load .env from project root (one level up from backend/)
load_dotenv(os.path.join(os.path.dirname(__file__), "..", "..", ".env"))

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
UPLOAD_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "uploads")
KEYFRAMES_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "keyframes")

# Ensure directories exist
os.makedirs(UPLOAD_DIR, exist_ok=True)
os.makedirs(KEYFRAMES_DIR, exist_ok=True)

# Shared OpenAI client with automatic retry on rate-limit (429) errors.
# max_retries=5 uses exponential backoff; the SDK reads the Retry-After
# header from the 429 response so it waits exactly the right amount of time.
# Higher retry count needed for low-tier API keys (3 RPM limit on gpt-4o-mini).
openai_client = AsyncOpenAI(api_key=OPENAI_API_KEY, max_retries=5)
