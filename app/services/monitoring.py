import logging
from contextlib import contextmanager
from typing import Any, Dict, Iterator, Literal, Optional

from langfuse import Langfuse

from app.core.config import settings

logger = logging.getLogger(__name__)

ObservationType = Literal[
    "span",
    "generation",
    "agent",
    "tool",
    "chain",
    "retriever",
    "evaluator",
    "embedding",
    "guardrail",
]


class MonitoringService:
    """Observability wrapper around Langfuse following OpenTelemetry nesting & best practices."""

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
        self._ensured_datasets: set[str] = set()

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

    @property
    def client(self) -> Optional[Langfuse]:
        """Return underlying Langfuse client if initialized."""
        return self._client

    def ensure_dataset(self, name: str, description: str = "") -> bool:
        """Idempotently ensure a Langfuse dataset exists."""
        if not self._client:
            return False
        if name in self._ensured_datasets:
            return True
        try:
            self._client.create_dataset(name=name, description=description or None)
            self._ensured_datasets.add(name)
            return True
        except Exception as exc:
            logger.debug(f"Langfuse ensure_dataset '{name}' skipped: {exc}")
            return False

    def log_dataset_item(
        self,
        dataset_name: str,
        input_data: Any,
        expected_output: Any,
        metadata: Optional[Dict[str, Any]] = None,
        source_trace_id: Optional[str] = None,
        source_observation_id: Optional[str] = None,
    ) -> None:
        """Create a Langfuse dataset item linked to its source trace/observation."""
        if not self._client:
            return
        self.ensure_dataset(dataset_name)
        try:
            self._client.create_dataset_item(
                dataset_name=dataset_name,
                input=input_data,
                expected_output=expected_output,
                metadata=metadata,
                source_trace_id=source_trace_id,
                source_observation_id=source_observation_id,
            )
        except Exception as exc:
            logger.debug(f"Langfuse log_dataset_item skipped: {exc}")

    def record_score(
        self,
        name: str,
        value: float | str,
        trace_id: Optional[str] = None,
        observation_id: Optional[str] = None,
        data_type: Literal["NUMERIC", "CATEGORICAL", "BOOLEAN"] = "NUMERIC",
        comment: Optional[str] = None,
    ) -> None:
        """Attach a Langfuse evaluation score to a trace or observation."""
        if not self._client or not trace_id:
            return
        try:
            self._client.create_score(
                name=name,
                value=value,
                trace_id=trace_id,
                observation_id=observation_id,
                data_type=data_type,
                comment=comment,
            )
        except Exception as exc:
            logger.debug(f"Langfuse record_score '{name}' skipped: {exc}")

    @contextmanager
    def trace_observation(
        self,
        name: str,
        as_type: ObservationType = "span",
        input_data: Any = None,
        metadata: Optional[Dict[str, Any]] = None,
        model: Optional[str] = None,
        model_parameters: Optional[Dict[str, Any]] = None,
        flush_on_exit: bool = False,
    ) -> Iterator[Optional[Any]]:
        """Context manager creating a properly typed, automatically nested Langfuse observation."""
        if not self._client:
            yield None
            return

        kwargs: Dict[str, Any] = {
            "name": name,
            "as_type": as_type,
            "input": input_data,
            "metadata": metadata,
        }
        if model is not None:
            kwargs["model"] = model
        if model_parameters is not None:
            kwargs["model_parameters"] = model_parameters

        try:
            with self._client.start_as_current_observation(**kwargs) as observation:
                yield observation
        except Exception as exc:
            logger.debug(f"Langfuse observation '{name}' skipped: {exc}")
            yield None
        finally:
            if flush_on_exit:
                self.flush()

    @contextmanager
    def trace_generation(
        self,
        name: str,
        model: str,
        input_data: Any,
        metadata: Optional[Dict[str, Any]] = None,
        model_parameters: Optional[Dict[str, Any]] = None,
        flush_on_exit: bool = False,
    ) -> Iterator[Optional[Any]]:
        """Convenience context manager for LLM generation observations."""
        with self.trace_observation(
            name=name,
            as_type="generation",
            input_data=input_data,
            metadata=metadata,
            model=model,
            model_parameters=model_parameters,
            flush_on_exit=flush_on_exit,
        ) as gen:
            yield gen

    @contextmanager
    def trace_span(
        self,
        name: str,
        input_data: Any = None,
        metadata: Optional[Dict[str, Any]] = None,
        flush_on_exit: bool = False,
    ) -> Iterator[Optional[Any]]:
        """Convenience context manager for generic span observations."""
        with self.trace_observation(
            name=name,
            as_type="span",
            input_data=input_data,
            metadata=metadata,
            flush_on_exit=flush_on_exit,
        ) as span:
            yield span

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
