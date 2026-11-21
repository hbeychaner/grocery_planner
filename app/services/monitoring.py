import logging
from contextlib import contextmanager
from typing import Any, Dict, Iterator, Optional

from langfuse import Langfuse

from app.core.config import settings

logger = logging.getLogger(__name__)


class MonitoringService:
    """Observability wrapper around Langfuse for tracing LLM calls and query pipelines."""

    def __init__(
        self,
        enabled: Optional[bool] = None,
        public_key: Optional[str] = None,
        secret_key: Optional[str] = None,
        host: Optional[str] = None,
    ) -> None:
        self.enabled = enabled if enabled is not None else settings.langfuse_enabled
        self.public_key = public_key or settings.langfuse_public_key
        self.secret_key = secret_key or settings.langfuse_secret_key
        self.host = host or settings.langfuse_host
        self._client: Optional[Langfuse] = None

        if self.enabled and self.public_key and self.secret_key:
            try:
                self._client = Langfuse(
                    public_key=self.public_key,
                    secret_key=self.secret_key,
                    base_url=self.host,
                    environment=settings.environment,
                    tracing_enabled=True,
                )
            except Exception as exc:
                logger.warning(f"Failed to initialize Langfuse client: {exc}")
                self._client = None
        elif self.enabled:
            logger.info("Langfuse enabled in config, but keys are missing; tracing inactive.")

    @property
    def is_active(self) -> bool:
        """Return True when Langfuse client is initialized and ready."""
        return self._client is not None

    @contextmanager
    def trace_generation(
        self,
        name: str,
        model: str,
        input_data: Any,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Iterator[Optional[Any]]:
        """Context manager tracing an LLM generation in Langfuse (no-op if inactive)."""
        if not self._client:
            yield None
            return

        try:
            with self._client.start_as_current_observation(
                name=name,
                as_type="generation",
                model=model,
                input=input_data,
                metadata=metadata,
            ) as observation:
                yield observation
        except Exception as exc:
            logger.debug(f"Langfuse generation trace skipped: {exc}")
            yield None
        finally:
            self.flush()

    @contextmanager
    def trace_span(
        self,
        name: str,
        input_data: Any = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Iterator[Optional[Any]]:
        """Context manager tracing a pipeline span in Langfuse (no-op if inactive)."""
        if not self._client:
            yield None
            return

        try:
            with self._client.start_as_current_observation(
                name=name,
                as_type="span",
                input=input_data,
                metadata=metadata,
            ) as span:
                yield span
        except Exception as exc:
            logger.debug(f"Langfuse span trace skipped: {exc}")
            yield None

    def flush(self) -> None:
        """Flush buffered Langfuse events."""
        if self._client:
            try:
                self._client.flush()
            except Exception:
                pass

    def shutdown(self) -> None:
        """Flush and close Langfuse background workers."""
        if self._client:
            try:
                self._client.shutdown()
            except Exception:
                pass
