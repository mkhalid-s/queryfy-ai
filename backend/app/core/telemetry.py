"""
QueryfyAI - OpenTelemetry Instrumentation

Centralized telemetry initialization for distributed tracing.
Supports auto-instrumentation for FastAPI, httpx, Redis.
Manual spans for LLM calls, database queries, agent execution.

Usage:
    from app.core.telemetry import init_telemetry, get_tracer

    # Initialize in main.py lifespan
    init_telemetry()

    # Get tracer for manual spans
    tracer = get_tracer(__name__)
    with tracer.start_as_current_span("my_operation") as span:
        span.set_attribute("key", "value")
"""

import logging
from contextlib import contextmanager
from typing import Optional

from app.core.config import settings
from app.core.version import __version__ as APP_VERSION

logger = logging.getLogger(__name__)

# Module-level state
_initialized = False
_tracer_provider = None


def init_telemetry() -> bool:
    """
    Initialize OpenTelemetry with OTLP exporter and auto-instrumentation.

    Returns:
        True if telemetry was initialized, False if disabled or already initialized.
    """
    global _initialized, _tracer_provider

    if _initialized:
        logger.debug("Telemetry already initialized")
        return False

    if not settings.OTEL_ENABLED:
        logger.info("OpenTelemetry disabled (OTEL_ENABLED=false)")
        _initialized = True
        return False

    try:
        from opentelemetry import trace
        from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import (
            OTLPSpanExporter,
        )
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor
        from opentelemetry.semconv.resource import ResourceAttributes

        # Create resource with service info
        resource = Resource.create(
            {
                ResourceAttributes.SERVICE_NAME: settings.OTEL_SERVICE_NAME,
                ResourceAttributes.SERVICE_VERSION: APP_VERSION,
                ResourceAttributes.DEPLOYMENT_ENVIRONMENT: (
                    "development" if settings.DEBUG else "production"
                ),
            }
        )

        # Create tracer provider
        _tracer_provider = TracerProvider(resource=resource)

        # Configure OTLP exporter
        otlp_exporter = OTLPSpanExporter(
            endpoint=settings.OTEL_EXPORTER_OTLP_ENDPOINT,
            insecure=True,  # Use insecure for local development
        )

        # Add batch processor for efficient export
        _tracer_provider.add_span_processor(BatchSpanProcessor(otlp_exporter))

        # Set as global tracer provider
        trace.set_tracer_provider(_tracer_provider)

        # Auto-instrument libraries
        _instrument_libraries()

        _initialized = True
        logger.info(
            f"OpenTelemetry initialized: service={settings.OTEL_SERVICE_NAME}, "
            f"endpoint={settings.OTEL_EXPORTER_OTLP_ENDPOINT}"
        )
        return True

    except ImportError as e:
        logger.warning(f"OpenTelemetry packages not installed: {e}")
        _initialized = True
        return False
    except Exception as e:
        logger.error(f"Failed to initialize OpenTelemetry: {e}")
        _initialized = True
        return False


def _instrument_libraries():
    """Auto-instrument common libraries."""

    # FastAPI
    try:
        from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

        FastAPIInstrumentor().instrument()
        logger.debug("Instrumented: FastAPI")
    except ImportError:
        pass
    except Exception as e:
        logger.warning(f"Failed to instrument FastAPI: {e}")

    # HTTPX (async HTTP client)
    try:
        from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor

        HTTPXClientInstrumentor().instrument()
        logger.debug("Instrumented: httpx")
    except ImportError:
        pass
    except Exception as e:
        logger.warning(f"Failed to instrument httpx: {e}")

    # Redis
    try:
        from opentelemetry.instrumentation.redis import RedisInstrumentor

        RedisInstrumentor().instrument()
        logger.debug("Instrumented: redis")
    except ImportError:
        pass
    except Exception as e:
        logger.warning(f"Failed to instrument redis: {e}")

    # Logging (inject trace context into logs)
    try:
        from opentelemetry.instrumentation.logging import LoggingInstrumentor

        LoggingInstrumentor().instrument(set_logging_format=False)
        logger.debug("Instrumented: logging")
    except ImportError:
        pass
    except Exception as e:
        logger.warning(f"Failed to instrument logging: {e}")


def get_tracer(name: str = __name__):
    """
    Get a tracer for manual instrumentation.

    Args:
        name: The tracer name, typically __name__ of the calling module.

    Returns:
        A tracer instance (or NoOpTracer if telemetry is disabled).
    """
    try:
        from opentelemetry import trace

        return trace.get_tracer(name)
    except ImportError:
        return _NoOpTracer()


def get_current_trace_id() -> Optional[str]:
    """
    Get the current trace ID as a hex string.

    Returns:
        The trace ID or None if no active span.
    """
    try:
        from opentelemetry import trace

        span = trace.get_current_span()
        if span and span.get_span_context().is_valid:
            return format(span.get_span_context().trace_id, "032x")
    except ImportError:
        pass
    return None


def get_current_span_id() -> Optional[str]:
    """
    Get the current span ID as a hex string.

    Returns:
        The span ID or None if no active span.
    """
    try:
        from opentelemetry import trace

        span = trace.get_current_span()
        if span and span.get_span_context().is_valid:
            return format(span.get_span_context().span_id, "016x")
    except ImportError:
        pass
    return None


def shutdown_telemetry():
    """Gracefully shutdown the tracer provider."""
    global _tracer_provider, _initialized

    if _tracer_provider:
        try:
            _tracer_provider.shutdown()
            logger.info("OpenTelemetry shutdown complete")
        except Exception as e:
            logger.warning(f"Error during telemetry shutdown: {e}")

    _tracer_provider = None
    _initialized = False


# NoOp implementations for when OpenTelemetry is disabled
class _NoOpSpan:
    """No-op span that does nothing."""

    def set_attribute(self, key, value):
        pass

    def set_status(self, status):
        pass

    def record_exception(self, exception):
        pass

    def add_event(self, name, attributes=None):
        pass

    def end(self):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass


class _NoOpTracer:
    """No-op tracer that returns no-op spans."""

    @contextmanager
    def start_as_current_span(self, name, **kwargs):
        yield _NoOpSpan()

    def start_span(self, name, **kwargs):
        return _NoOpSpan()


# Convenience function for creating spans with common LLM attributes
@contextmanager
def trace_llm_call(operation: str, provider: str, model: str):
    """
    Context manager for tracing LLM calls with standard attributes.

    Usage:
        with trace_llm_call("generate_sql", "openai", "gpt-4") as span:
            result = await llm.generate(...)
            span.set_attribute("llm.tokens.input", 100)
    """
    tracer = get_tracer("queryfyai.llm")
    with tracer.start_as_current_span(f"llm.{operation}") as span:
        span.set_attribute("llm.provider", provider)
        span.set_attribute("llm.model", model)
        span.set_attribute("llm.operation", operation)
        yield span


@contextmanager
def trace_db_operation(operation: str, db_type: str, db_name: Optional[str] = None):
    """
    Context manager for tracing database operations with standard attributes.

    Usage:
        with trace_db_operation("execute_query", "postgresql", "mydb") as span:
            result = await db.execute(query)
            span.set_attribute("db.rows_returned", len(result))
    """
    tracer = get_tracer("queryfyai.database")
    with tracer.start_as_current_span(f"db.{operation}") as span:
        span.set_attribute("db.system", db_type)
        span.set_attribute("db.operation", operation)
        if db_name:
            span.set_attribute("db.name", db_name)
        yield span


@contextmanager
def trace_agent_step(step_name: str, attempt: int = 0):
    """
    Context manager for tracing agent execution steps.

    Usage:
        with trace_agent_step("validate_sql", attempt=1) as span:
            result = await validate(sql)
            span.set_attribute("agent.success", True)
    """
    tracer = get_tracer("queryfyai.agent")
    with tracer.start_as_current_span(f"agent.{step_name}") as span:
        span.set_attribute("agent.step", step_name)
        span.set_attribute("agent.attempt", attempt)
        yield span
