#!/bin/bash

# Start script for Redis and Celery workers
# For hackathon/demo use - in production use proper process managers

echo "🚀 Starting Compliance Vision background services..."

# Check if Redis is installed
if ! command -v redis-server &> /dev/null; then
    echo "❌ Redis not found. Please install Redis first:"
    echo "   macOS: brew install redis"
    echo "   Ubuntu: sudo apt-get install redis-server"
    exit 1
fi

# Check if virtual environment exists
if [ ! -d ".venv" ]; then
    echo "❌ Virtual environment not found. Please run setup first:"
    echo "   python -m venv .venv"
    echo "   source .venv/bin/activate"
    echo "   pip install -r backend/requirements.txt"
    exit 1
fi

# Activate virtual environment
source .venv/bin/activate

# Start Redis in background
echo "Starting Redis..."
redis-server --daemonize yes --port 6379 --logfile redis.log

# Wait for Redis to start
sleep 2

# Check if Redis is running
if redis-cli ping > /dev/null 2>&1; then
    echo "✅ Redis started successfully"
else
    echo "❌ Failed to start Redis"
    exit 1
fi

# Start Celery worker in background
echo "Starting Celery worker..."
celery -A backend.services.celery_app worker \
    --loglevel=info \
    --concurrency=2 \
    --pool=threads \
    --logfile=celery.log \
    --detach

# Start Celery beat for periodic tasks (optional)
# celery -A backend.services.celery_app beat \
#     --loglevel=info \
#     --logfile=celery-beat.log \
#     --detach

echo "✅ All services started!"
echo ""
echo "📝 Log files:"
echo "   - Redis: redis.log"
echo "   - Celery: celery.log"
echo ""
echo "To stop services:"
echo "   redis-cli shutdown"
echo "   pkill -f 'celery worker'"
echo ""
echo "Now start the backend and frontend:"
echo "   Terminal 1: uvicorn backend.main:app --reload --port 8082"
echo "   Terminal 2: cd frontend && npm run dev"