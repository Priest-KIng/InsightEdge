from __future__ import annotations

import logging
import time
from uuid import uuid4

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
import structlog


def configure_logging() -> None:
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.stdlib.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.stdlib.BoundLogger,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )
    logging.basicConfig(level=logging.INFO, format="%(message)s")


class RequestContextMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):  # type: ignore[override]
        request_id = request.headers.get("x-request-id") or str(uuid4())
        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(
            request_id=request_id,
            method=request.method,
            path=request.url.path,
        )
        request.state.request_id = request_id

        logger = structlog.get_logger("http")
        start = time.perf_counter()
        response = None
        try:
            response = await call_next(request)
            return response
        except Exception:
            logger.exception("request_failed")
            raise
        finally:
            duration_ms = round((time.perf_counter() - start) * 1000, 2)
            if response is not None:
                response.headers["X-Request-ID"] = request_id
                logger.info(
                    "request_completed",
                    status_code=response.status_code,
                    duration_ms=duration_ms,
                )
            else:
                logger.info("request_completed", status_code=500, duration_ms=duration_ms)
            structlog.contextvars.clear_contextvars()
