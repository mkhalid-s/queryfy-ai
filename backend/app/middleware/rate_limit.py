"""
QueryfyAI - Rate Limiting with SlowAPI

Provides IP-based and endpoint-based rate limiting:
- Default: 100 requests/minute
- LLM endpoints: 30 requests/minute (expensive)
- Query execution: 60 requests/minute
- Export: 10 requests/minute

Backend: Redis if available, memory fallback

Usage in endpoints:
    from app.middleware.rate_limit import limiter

    @router.post("/query/generate")
    @limiter.limit("30/minute")
    async def generate_query(request: Request, ...):
        ...
"""

import logging
from typing import Callable, Optional

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from slowapi import Limiter
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from slowapi.util import get_remote_address

logger = logging.getLogger(__name__)


def get_real_ip(request: Request) -> str:
    """
    Get real client IP, handling proxies and load balancers.

    Priority:
    1. X-Forwarded-For header (first IP)
    2. X-Real-IP header
    3. Client host from connection
    """
    # Check X-Forwarded-For (common in proxy/LB setups)
    forwarded_for = request.headers.get("X-Forwarded-For")
    if forwarded_for:
        # Take the first IP (original client)
        return forwarded_for.split(",")[0].strip()

    # Check X-Real-IP (nginx)
    real_ip = request.headers.get("X-Real-IP")
    if real_ip:
        return real_ip.strip()

    # Fall back to connection client
    return get_remote_address(request)


def get_session_key(request: Request) -> str:
    """
    Rate limit by session ID if available, otherwise by IP.
    This allows per-session rate limiting when logged in.
    """
    # Try to get session_id from query params or body
    session_id = request.query_params.get("session_id")
    if session_id:
        return f"session:{session_id}"

    # Fall back to IP
    return get_real_ip(request)


# Create limiter with memory backend (will be updated with Redis if available)
limiter = Limiter(
    key_func=get_real_ip,
    default_limits=["100/minute"],
    storage_uri="memory://",
    strategy="fixed-window",
)


# Rate limit configurations for different endpoint types
RATE_LIMITS = {
    # LLM operations (expensive)
    "llm_generate": "30/minute",
    "llm_explain": "30/minute",
    # Database operations
    "query_execute": "60/minute",
    "schema_extract": "20/minute",
    # Export operations (resource intensive)
    "export": "10/minute",
    # Session operations
    "session_create": "20/minute",
    # Admin/health (generous limits)
    "health": "200/minute",
}


async def rate_limit_exceeded_handler(
    request: Request, exc: Exception
) -> JSONResponse:
    """
    Custom handler for rate limit exceeded errors.
    Returns a JSON response with retry information.
    """
    # Extract retry-after from the exception if available
    retry_after = getattr(exc, "retry_after", 60)

    detail = getattr(exc, "detail", "Rate limit exceeded")

    logger.warning(
        f"Rate limit exceeded: {get_real_ip(request)} - "
        f"{request.method} {request.url.path} - "
        f"Limit: {detail}"
    )

    return JSONResponse(
        status_code=429,
        content={
            "error": "rate_limit_exceeded",
            "message": f"Too many requests. Please try again in {retry_after} seconds.",
            "detail": str(detail),
            "retry_after_seconds": retry_after,
        },
        headers={
            "Retry-After": str(retry_after),
            "X-RateLimit-Limit": str(detail),
        },
    )


def setup_rate_limiting(
    app: FastAPI,
    redis_url: Optional[str] = None,
    enabled: bool = True,
    default_limit: str = "100/minute",
) -> Limiter:
    """
    Configure rate limiting for the FastAPI application.

    Args:
        app: FastAPI application instance
        redis_url: Redis URL for distributed rate limiting (optional)
        enabled: Whether rate limiting is enabled
        default_limit: Default rate limit string

    Returns:
        Configured Limiter instance
    """
    global limiter

    if not enabled:
        logger.info("Rate limiting is disabled")
        # Create a no-op limiter
        limiter = Limiter(key_func=get_real_ip, enabled=False)
        return limiter

    # Determine storage backend
    storage_uri = "memory://"
    if redis_url and redis_url.strip():
        storage_uri = redis_url
        logger.info("Rate limiting using Redis backend")
    else:
        logger.info("Rate limiting using in-memory backend")

    # Create limiter with configuration
    limiter = Limiter(
        key_func=get_real_ip,
        default_limits=[default_limit],
        storage_uri=storage_uri,
        strategy="fixed-window",
        headers_enabled=True,  # Include rate limit headers in responses
    )

    # Attach limiter to app state
    app.state.limiter = limiter

    # Add exception handler
    app.add_exception_handler(RateLimitExceeded, rate_limit_exceeded_handler)

    # Add middleware
    app.add_middleware(SlowAPIMiddleware)

    logger.info(f"Rate limiting configured: default={default_limit}")
    return limiter


# Helper decorators for common rate limits
def limit_llm(func: Callable) -> Callable:
    """Decorator for LLM endpoints (30/minute)"""
    return limiter.limit(RATE_LIMITS["llm_generate"])(func)


def limit_query(func: Callable) -> Callable:
    """Decorator for query execution endpoints (60/minute)"""
    return limiter.limit(RATE_LIMITS["query_execute"])(func)


def limit_export(func: Callable) -> Callable:
    """Decorator for export endpoints (10/minute)"""
    return limiter.limit(RATE_LIMITS["export"])(func)


def limit_session(func: Callable) -> Callable:
    """Decorator for session creation (20/minute)"""
    return limiter.limit(RATE_LIMITS["session_create"])(func)
