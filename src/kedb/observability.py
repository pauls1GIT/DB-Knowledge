"""Optional SDK integration. Never include ticket content in span metadata."""
from contextlib import nullcontext
from functools import wraps
import logging
from threading import Lock

from kedb.config import Settings

logger = logging.getLogger(__name__)
_sdk = None
_lock = Lock()


def initialize(settings: Settings | None = None):
    global _sdk
    with _lock:
        if _sdk is not None:
            return _sdk
        settings = settings or Settings()
        if not settings.kedb_observability_enabled:
            return None
        if (not settings.ai_observability_endpoint
                or not settings.ai_observability_api_key.get_secret_value()):
            logger.warning("Observability requires an endpoint and ingest API key")
            return None
        try:
            import ai_observability

            ai_observability.init(
                service_name="known-error-curator",
                service_version="0.1.0",
                deployment_environment=settings.kedb_env,
                endpoint=settings.ai_observability_endpoint,
                api_key=settings.ai_observability_api_key.get_secret_value(),
                capture_prompts=False,
            )
            _sdk = ai_observability
        except Exception:
            logger.warning("Observability initialization failed; tracing disabled")
        return _sdk


def shutdown():
    global _sdk
    with _lock:
        if _sdk is not None:
            try:
                if not _sdk.flush(timeout_millis=5000):
                    logger.warning("Observability flush did not deliver all telemetry")
                _sdk.shutdown()
            except Exception:
                logger.warning("Observability shutdown failed")
            finally:
                _sdk = None


def execution(name: str, workflow_id: str | None = None):
    sdk = initialize()
    if sdk is None:
        return nullcontext()
    return sdk.workflow(name=name, workflow_id=workflow_id, version="v1")


def traced_step(name: str):
    def decorate(function):
        @wraps(function)
        def wrapped(*args, **kwargs):
            sdk = initialize()
            with sdk.span(name=name) if sdk else nullcontext():
                return function(*args, **kwargs)
        return wrapped
    return decorate
