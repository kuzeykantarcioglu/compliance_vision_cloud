"""Utilities for API calls with retry logic, rate limiting, and usage tracking."""

import asyncio
import logging
import time
from typing import Any, Callable, Optional, TypeVar, Dict
from functools import wraps
import json

logger = logging.getLogger(__name__)

T = TypeVar('T')

# Global usage tracker (in production, use Redis or database)
usage_tracker: Dict[str, Dict[str, Any]] = {}

class APIError(Exception):
    """Custom exception for API-related errors."""
    pass

class RateLimitError(APIError):
    """Raised when rate limit is exceeded."""
    pass

async def exponential_backoff_retry(
    func: Callable,
    max_retries: int = 3,
    initial_delay: float = 1.0,
    max_delay: float = 60.0,
    exponential_base: float = 2.0,
    jitter: bool = True,
    service_name: str = "API",
) -> Any:
    """
    Execute an async function with exponential backoff retry logic.
    
    Args:
        func: Async function to execute
        max_retries: Maximum number of retry attempts
        initial_delay: Initial delay between retries in seconds
        max_delay: Maximum delay between retries
        exponential_base: Base for exponential backoff
        jitter: Add random jitter to prevent thundering herd
        service_name: Name of service for logging
    
    Returns:
        Result from successful function execution
        
    Raises:
        Last exception if all retries fail
    """
    delay = initial_delay
    last_exception = None
    
    for attempt in range(max_retries + 1):
        try:
            result = await func()
            if attempt > 0:
                logger.info(f"✅ {service_name} succeeded after {attempt} retries")
            return result
            
        except asyncio.CancelledError:
            # Don't retry on cancellation
            raise
            
        except Exception as e:
            last_exception = e
            
            # Check if error is retryable
            error_msg = str(e).lower()
            non_retryable = [
                "invalid api key",
                "authentication",
                "insufficient_quota",
                "invalid_request",
                "content_policy_violation",
            ]
            
            if any(term in error_msg for term in non_retryable):
                logger.error(f"❌ {service_name} non-retryable error: {e}")
                raise
            
            if attempt < max_retries:
                # Add jitter to prevent thundering herd
                actual_delay = delay
                if jitter:
                    import random
                    actual_delay = delay * (0.5 + random.random())
                
                logger.warning(
                    f"⚠️ {service_name} attempt {attempt + 1}/{max_retries + 1} failed: {e}. "
                    f"Retrying in {actual_delay:.1f}s..."
                )
                
                await asyncio.sleep(actual_delay)
                
                # Exponential backoff
                delay = min(delay * exponential_base, max_delay)
            else:
                logger.error(f"❌ {service_name} failed after {max_retries} retries: {e}")
    
    raise last_exception


def track_usage(
    service: str,
    tokens: Optional[int] = None,
    cost: Optional[float] = None,
    metadata: Optional[Dict] = None
):
    """
    Track API usage for billing and monitoring.
    
    In production, this would write to Redis/PostgreSQL.
    For hackathon, we'll use in-memory tracking.
    """
    timestamp = time.time()
    
    if service not in usage_tracker:
        usage_tracker[service] = {
            "total_calls": 0,
            "total_tokens": 0,
            "total_cost": 0.0,
            "calls_per_minute": [],
            "last_reset": timestamp,
        }
    
    tracker = usage_tracker[service]
    tracker["total_calls"] += 1
    
    if tokens:
        tracker["total_tokens"] += tokens
    
    if cost:
        tracker["total_cost"] += cost
    
    # Track calls per minute for rate limiting
    current_minute = int(timestamp / 60)
    tracker["calls_per_minute"] = [
        (t, c) for t, c in tracker.get("calls_per_minute", [])
        if current_minute - t < 5  # Keep last 5 minutes
    ]
    
    # Add current call
    calls_this_minute = sum(
        c for t, c in tracker["calls_per_minute"] 
        if t == current_minute
    )
    
    if calls_this_minute == 0:
        tracker["calls_per_minute"].append((current_minute, 1))
    else:
        tracker["calls_per_minute"] = [
            (t, c + 1 if t == current_minute else c)
            for t, c in tracker["calls_per_minute"]
        ]
    
    logger.debug(
        f"📊 {service} usage - Calls: {tracker['total_calls']}, "
        f"Tokens: {tracker['total_tokens']}, Cost: ${tracker['total_cost']:.4f}"
    )


def check_rate_limit(
    service: str,
    max_per_minute: int = 60,
    max_per_hour: int = 1000,
) -> bool:
    """
    Check if rate limit would be exceeded.
    
    Returns:
        True if within limits, False if exceeded
    """
    if service not in usage_tracker:
        return True
    
    tracker = usage_tracker[service]
    current_minute = int(time.time() / 60)
    
    # Check per-minute limit
    calls_last_minute = sum(
        c for t, c in tracker.get("calls_per_minute", [])
        if t == current_minute
    )
    
    if calls_last_minute >= max_per_minute:
        logger.warning(f"⚠️ {service} rate limit: {calls_last_minute}/{max_per_minute} per minute")
        return False
    
    # Check per-hour limit (last 60 minutes)
    calls_last_hour = sum(
        c for t, c in tracker.get("calls_per_minute", [])
        if current_minute - t < 60
    )
    
    if calls_last_hour >= max_per_hour:
        logger.warning(f"⚠️ {service} rate limit: {calls_last_hour}/{max_per_hour} per hour")
        return False
    
    return True


def get_usage_stats() -> Dict[str, Any]:
    """Get current usage statistics for all services."""
    stats = {}
    for service, data in usage_tracker.items():
        stats[service] = {
            "total_calls": data["total_calls"],
            "total_tokens": data["total_tokens"],
            "total_cost": round(data["total_cost"], 4),
            "recent_calls": sum(c for _, c in data.get("calls_per_minute", [])),
        }
    return stats


def estimate_cost(
    service: str,
    input_tokens: int = 0,
    output_tokens: int = 0,
    model: str = "gpt-4o",
) -> float:
    """
    Estimate cost for API call based on token usage.
    
    Prices as of Feb 2024 (update as needed):
    """
    pricing = {
        "gpt-4o": {"input": 0.00250, "output": 0.01000},  # per 1K tokens
        "gpt-4o-mini": {"input": 0.00015, "output": 0.00060},
        "whisper": {"per_minute": 0.006},
        "gpt-4-vision": {"input": 0.01, "output": 0.03},
    }
    
    if model not in pricing:
        return 0.0
    
    if service == "whisper":
        # Whisper is billed per minute of audio
        return pricing["whisper"]["per_minute"] * (input_tokens / 60.0)
    
    price = pricing[model]
    cost = (input_tokens * price["input"] / 1000) + (output_tokens * price["output"] / 1000)
    
    return cost