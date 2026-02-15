#!/bin/bash

echo "🛑 Stopping Agent 00Vision..."

# Kill processes from PID file
if [ -f .pids ]; then
    while read pid; do
        kill -9 $pid 2>/dev/null
    done < .pids
    rm .pids
fi

# Also kill any stragglers by port
lsof -ti:8000 | xargs kill -9 2>/dev/null
lsof -ti:5173 | xargs kill -9 2>/dev/null

# Kill any remaining python/node processes related to our app
pkill -f "uvicorn backend.main:app" 2>/dev/null
pkill -f "npm run dev" 2>/dev/null
pkill -f "celery.*backend.services" 2>/dev/null

echo "✅ All services stopped"