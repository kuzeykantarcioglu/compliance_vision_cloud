#!/bin/bash

# Agent 00Vision - One-click startup script

echo "🕵️‍♂️ Starting Agent 00Vision..."

# Check if .env exists
if [ ! -f .env ]; then
    echo "⚠️  No .env file found! Creating one..."
    echo "Enter your OpenAI API key:"
    read -r api_key
    echo "OPENAI_API_KEY=$api_key" > .env
fi

# Kill any existing processes on our ports
echo "🧹 Cleaning up old processes..."
lsof -ti:8000 | xargs kill -9 2>/dev/null
lsof -ti:5173 | xargs kill -9 2>/dev/null

# Create/activate virtual environment
if [ ! -d "venv" ]; then
    echo "📦 Creating virtual environment..."
    python3 -m venv venv
fi

# Install backend dependencies
echo "📦 Installing backend dependencies..."
source venv/bin/activate
pip install -r backend/requirements.txt -q

# Install frontend dependencies if needed
if [ ! -d "frontend/node_modules" ]; then
    echo "📦 Installing frontend dependencies..."
    cd frontend && npm install && cd ..
fi

# Start backend in background
echo "🚀 Starting backend..."
PYTHONPATH=$(pwd) uvicorn backend.main:app --reload --host 0.0.0.0 --port 8000 > backend.log 2>&1 &
BACKEND_PID=$!

# Start frontend in background
echo "🚀 Starting frontend..."
cd frontend && npm run dev > ../frontend.log 2>&1 &
FRONTEND_PID=$!
cd ..

# Optional: Start Redis if installed
if command -v redis-server &> /dev/null; then
    echo "🔄 Starting Redis..."
    redis-server > redis.log 2>&1 &
    REDIS_PID=$!
    
    # Start Celery worker
    echo "🔄 Starting Celery worker..."
    celery -A backend.services.celery_app worker --loglevel=info > celery.log 2>&1 &
    CELERY_PID=$!
fi

echo ""
echo "✅ Agent 00Vision is running!"
echo ""
echo "🌐 Frontend: http://localhost:5173"
echo "🔧 Backend API: http://localhost:8000"
echo "📚 API Docs: http://localhost:8000/docs"
echo ""
echo "📋 Process IDs saved to .pids"
echo "Backend: $BACKEND_PID"
echo "Frontend: $FRONTEND_PID"
[ ! -z "$REDIS_PID" ] && echo "Redis: $REDIS_PID"
[ ! -z "$CELERY_PID" ] && echo "Celery: $CELERY_PID"
echo ""
echo "To stop all services: ./stop.sh"
echo "To view logs: tail -f *.log"
echo ""

# Save PIDs for stop script
echo "$BACKEND_PID" > .pids
echo "$FRONTEND_PID" >> .pids
[ ! -z "$REDIS_PID" ] && echo "$REDIS_PID" >> .pids
[ ! -z "$CELERY_PID" ] && echo "$CELERY_PID" >> .pids

# Keep script running and show logs
echo "Press Ctrl+C to stop all services..."
trap 'echo "Stopping..."; ./stop.sh; exit' INT

# Follow backend logs
tail -f backend.log frontend.log 2>/dev/null