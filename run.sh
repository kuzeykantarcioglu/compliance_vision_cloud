#!/bin/bash

# Agent 00Vision - Cloud Mode (no Redis/Celery required)

cd "$(dirname "$0")"

# --- .env setup ---
if [ ! -f .env ]; then
    echo "No .env file found. Enter your OpenAI API key:"
    read -r api_key
    echo "OPENAI_API_KEY=$api_key" > .env
fi

# --- Kill old processes on our ports ---
lsof -ti:8082 | xargs kill -9 2>/dev/null
lsof -ti:5173 | xargs kill -9 2>/dev/null

# --- Python venv + deps ---
if [ ! -d "venv" ]; then
    echo "Creating virtual environment..."
    python3 -m venv venv
fi
source venv/bin/activate
pip install -r backend/requirements.txt -q

# --- Frontend deps ---
if [ ! -d "frontend/node_modules" ]; then
    echo "Installing frontend dependencies..."
    (cd frontend && npm install)
fi

# --- Start backend on port 8082 (matches Vite proxy) ---
echo "Starting backend on :8082..."
PYTHONPATH=$(pwd) uvicorn backend.main:app --reload --host 0.0.0.0 --port 8082 > backend.log 2>&1 &
BACKEND_PID=$!

# --- Start frontend on port 5173 ---
echo "Starting frontend on :5173..."
(cd frontend && npm run dev) > frontend.log 2>&1 &
FRONTEND_PID=$!

# --- Wait for backend to be ready ---
echo "Waiting for backend..."
for i in $(seq 1 30); do
    if curl -s http://localhost:8082/health > /dev/null 2>&1; then
        echo ""
        echo "Agent 00Vision is running!"
        echo ""
        echo "  Frontend: http://localhost:5173"
        echo "  Backend:  http://localhost:8082"
        echo "  API Docs: http://localhost:8082/docs"
        echo ""
        break
    fi
    sleep 1
    printf "."
done

# --- Save PIDs for cleanup ---
echo "$BACKEND_PID" > .pids
echo "$FRONTEND_PID" >> .pids

echo "Press Ctrl+C to stop..."
trap "kill $BACKEND_PID $FRONTEND_PID 2>/dev/null; rm -f .pids; echo 'Stopped.'; exit" INT TERM

wait
