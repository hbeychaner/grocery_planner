import asyncio
import json
import logging
import re
from typing import Any, Dict, List, Optional
import httpx
from pydantic import BaseModel, Field, field_validator

from app.core.config import settings
from app.services.monitoring import MonitoringService

logger = logging.getLogger(__name__)


class OllamaQueryAnalysis(BaseModel):
    """Structured LLM analysis of a grocery query with strict per-language metadata."""

    source_language: str = Field(default="en", description="Detected ISO 639-1 source language code")
    translations: Dict[str, str] = Field(
        default_factory=dict,
        description="Strict per-language grocery search term (e.g. {'en': 'sourdough bread', 'cs': 'kváskový chléb'})",
    )
    category: Optional[str] = Field(
        default=None,
        description="Standardized English grocery category slug",
    )
    labels: Dict[str, List[str]] = Field(
        default_factory=dict,
        description="Strict per-language descriptive tags",
    )
    synonyms: Dict[str, List[str]] = Field(
        default_factory=dict,
        description="Strict per-language synonymous search terms",
    )
    is_compound: bool = Field(
        default=True,
        description="True if the input query represents a single unified product concept",
    )

    @field_validator("translations", mode="before")
    @classmethod
    def _coerce_translations(cls, v: Any) -> Dict[str, str]:
        if isinstance(v, dict):
            return {str(k).lower(): str(val).strip() for k, val in v.items() if val}
        return {}

    @property
    def query_cs(self) -> str:
        """Convenience accessor for the Czech catalog search term."""
        return self.translations.get("cs", "")

    def get_translation(self, lang: str) -> Optional[str]:
        """Return translated term for a specific ISO 639-1 language code."""
        return self.translations.get(lang.lower())


class OllamaService:
    """Client for local Ollama LLM handling unstructured NLP work with Langfuse tracing."""

    def __init__(
        self,
        base_url: Optional[str] = None,
        model: Optional[str] = None,
        timeout: Optional[float] = None,
        enabled: Optional[bool] = None,
        think: Optional[bool] = None,
        max_concurrency: Optional[int] = None,
        monitoring: Optional[MonitoringService] = None,
    ) -> None:
        self.base_url = (base_url or settings.ollama_base_url).rstrip("/")
        self.model = model or settings.ollama_model
        self.timeout = timeout or settings.ollama_timeout_seconds
        self.enabled = enabled if enabled is not None else settings.ollama_enabled
        self.think = think if think is not None else settings.ollama_think
        self.max_concurrency = max(1, max_concurrency if max_concurrency is not None else settings.ollama_max_concurrency)
        self.monitoring = monitoring or MonitoringService()
        self._http_client: Optional[httpx.AsyncClient] = None
        self._semaphore: Optional[asyncio.Semaphore] = None
        self._semaphore_loop: Optional[asyncio.AbstractEventLoop] = None

    def _get_semaphore(self) -> asyncio.Semaphore:
        """Return a per-event-loop Semaphore to queue local LLM requests safely."""
        loop = asyncio.get_running_loop()
        if self._semaphore is None or self._semaphore_loop is not loop:
            self._semaphore = asyncio.Semaphore(self.max_concurrency)
            self._semaphore_loop = loop
        return self._semaphore

    async def _get_client(self) -> httpx.AsyncClient:
        if self._http_client is None or self._http_client.is_closed:
            self._http_client = httpx.AsyncClient(
                base_url=self.base_url,
                timeout=self.timeout,
            )
        return self._http_client

    @staticmethod
    def _extract_json(raw_text: str) -> Dict[str, Any]:
        """Parse JSON from LLM output, stripping markdown code fences if present."""
        cleaned = raw_text.strip()
        fence_match = re.search(r"```(?:json)?\s*(\{.*\})\s*```", cleaned, flags=re.DOTALL)
        if fence_match:
            cleaned = fence_match.group(1).strip()
        else:
            start = cleaned.find("{")
            end = cleaned.rfind("}")
            if start != -1 and end != -1 and end > start:
                cleaned = cleaned[start : end + 1]
        data = json.loads(cleaned)
        if not isinstance(data, dict):
            raise ValueError("Expected JSON object from LLM response")
        return data

    async def health_check(self) -> bool:
        """Check if local Ollama server is reachable and responsive."""
        if not self.enabled:
            return False
        try:
            client = await self._get_client()
            resp = await client.get("/api/tags")
            return resp.status_code == 200
        except Exception:
            return False

    async def analyze_query(
        self,
        query: str,
        target_languages: Optional[List[str]] = None,
    ) -> Optional[OllamaQueryAnalysis]:
        """Translate and classify a grocery query with strict per-language metadata separation."""
        if not self.enabled:
            return None

        langs = target_languages or settings.supported_languages
        langs_list = ", ".join(f'"{lang}"' for lang in langs)
        translations_example = ", ".join(
            f'"{lang}": "<natural grocery search keyword strictly in {lang}>"' for lang in langs
        )
        labels_example = ", ".join(
            f'"{lang}": ["<tag1 strictly in {lang}>", "<tag2 strictly in {lang}>"]' for lang in langs
        )
        synonyms_example = ", ".join(
            f'"{lang}": ["<synonym strictly in {lang}>"]' for lang in langs
        )

        prompt = f"""Grocery query: "{query.strip()}"
Rules: Keep each language key ({langs_list}) strictly in that language. No weights/numbers unless in input. "category" is one English slug: dairy, milk_alternatives, bakery, produce, beverages, meat, seafood, pantry, snacks, frozen, household, other.
Return ONLY JSON:
{{"source_language":"<iso>","translations":{{{translations_example}}},"category":"<slug>","labels":{{{labels_example}}},"synonyms":{{{synonyms_example}}},"is_compound":true}}"""

        model_params = {"num_predict": 256, "temperature": 0.1, "think": self.think}
        with self.monitoring.trace_generation(
            name="translate-and-classify-query",
            model=self.model,
            input_data=[{"role": "user", "content": prompt}],
            metadata={"query": query, "target_languages": langs},
            model_parameters=model_params,
        ) as span:
            try:
                client = await self._get_client()
                payload: Dict[str, Any] = {
                    "model": self.model,
                    "prompt": prompt,
                    "think": self.think,
                    "stream": False,
                    "options": {"num_predict": 256, "temperature": 0.1},
                }
                async with self._get_semaphore():
                    resp = await client.post("/api/generate", json=payload)
                if resp.status_code == 200:
                    body = resp.json()
                    raw_response = body.get("response", "{}")
                    data = self._extract_json(raw_response)

                    # Support legacy flat query_cs fallback if model returned it
                    if "query_cs" in data and "translations" not in data:
                        data["translations"] = {"cs": data.pop("query_cs")}
                    if isinstance(data.get("labels"), list):
                        src_lang = str(data.get("source_language", "en")).lower()
                        data["labels"] = {src_lang: data["labels"]}
                    if isinstance(data.get("synonyms"), list):
                        data["synonyms"] = {"cs": data["synonyms"]}

                    analysis = OllamaQueryAnalysis.model_validate(data)
                    if analysis.translations:
                        if span is not None:
                            span.update(
                                output={"role": "assistant", "content": raw_response},
                                metadata={"parsed": analysis.model_dump()},
                                usage_details={
                                    "input": int(body.get("prompt_eval_count", 0)),
                                    "output": int(body.get("eval_count", 0)),
                                },
                            )
                        return analysis
            except Exception as exc:
                logger.debug(f"Ollama query analysis skipped or failed: {exc}")
                if span is not None:
                    span.update(level="WARNING", status_message=str(exc))

        return None

    async def filter_relevant_indices(
        self,
        query: str,
        titles: List[str],
        query_cs: Optional[str] = None,
    ) -> Optional[List[int]]:
        """Ask LLM which candidate product titles actually ARE the requested grocery item."""
        if not self.enabled or not titles:
            return None

        items_str = "\n".join(f"{i}: {title}" for i, title in enumerate(titles))
        query_label = f'"{query}" (Czech: "{query_cs}")' if query_cs and query_cs.lower() != query.lower() else f'"{query}"'
        prompt = f"""Requested grocery item: {query_label}
Candidate products:
{items_str}

Select ONLY the indices of products that ARE the requested item itself (plain/fresh/standard form).
STRICTLY EXCLUDE different products that merely contain it as a flavor, ingredient, or derivative:
- e.g. for "blueberries" / "borůvky": include fresh or frozen blueberries, EXCLUDE blueberry kefir, skyr, yogurt, jam, tea, or juice.
- e.g. for "butter" / "máslo": include dairy butter, EXCLUDE butter cookies, peanut butter, or cocoa butter.
- e.g. for "chicken breast" / "kuřecí prsa": include chicken breast meat, EXCLUDE chicken broth, soup, or cat food.
Return ONLY valid JSON: {{"relevant_indices": [0, 1]}}"""

        model_params = {"num_predict": 128, "temperature": 0.0, "think": self.think}
        with self.monitoring.trace_generation(
            name="filter-relevant-candidates",
            model=self.model,
            input_data=[{"role": "user", "content": prompt}],
            metadata={"query": query, "query_cs": query_cs, "candidate_count": len(titles)},
            model_parameters=model_params,
        ) as span:
            try:
                client = await self._get_client()
                payload: Dict[str, Any] = {
                    "model": self.model,
                    "prompt": prompt,
                    "think": self.think,
                    "stream": False,
                    "options": {"num_predict": 128, "temperature": 0.0},
                }
                async with self._get_semaphore():
                    resp = await client.post("/api/generate", json=payload)
                if resp.status_code == 200:
                    body = resp.json()
                    raw_response = body.get("response", "{}")
                    data = self._extract_json(raw_response)
                    indices = data.get("relevant_indices")
                    if isinstance(indices, list):
                        valid = [
                            int(i)
                            for i in indices
                            if isinstance(i, (int, str)) and str(i).isdigit() and 0 <= int(i) < len(titles)
                        ]
                        if span is not None:
                            span.update(
                                output={"role": "assistant", "content": raw_response},
                                metadata={"relevant_indices": valid},
                                usage_details={
                                    "input": int(body.get("prompt_eval_count", 0)),
                                    "output": int(body.get("eval_count", 0)),
                                },
                            )
                        return valid
            except Exception as exc:
                logger.debug(f"Ollama candidate filtering skipped: {exc}")
                if span is not None:
                    span.update(level="WARNING", status_message=str(exc))

        return None

    async def close(self) -> None:
        """Close connection pool."""
        if self._http_client and not self._http_client.is_closed:
            await self._http_client.aclose()
