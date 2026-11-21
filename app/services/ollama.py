import json
import logging
from typing import List, Optional
import httpx
from pydantic import BaseModel, Field
from app.core.config import settings

logger = logging.getLogger(__name__)


class OllamaQueryAnalysis(BaseModel):
    """Structured LLM analysis of a grocery query."""

    query_cs: str = Field(..., description="Natural Czech translation for supermarket search catalogs")
    category: Optional[str] = Field(default=None, description="Broad food category (e.g. dairy, bakery, produce)")
    labels: List[str] = Field(default_factory=list, description="Descriptive labels (organic, sourdough, etc.)")
    synonyms: List[str] = Field(default_factory=list, description="Synonymous Czech terms")


class OllamaService:
    """Client for local Ollama LLM handling unstructured NLP work (translation, labeling, filtering)."""

    def __init__(
        self,
        base_url: Optional[str] = None,
        model: Optional[str] = None,
        timeout: Optional[float] = None,
        enabled: Optional[bool] = None,
    ) -> None:
        self.base_url = (base_url or settings.ollama_base_url).rstrip("/")
        self.model = model or settings.ollama_model
        self.timeout = timeout or settings.ollama_timeout_seconds
        self.enabled = enabled if enabled is not None else settings.ollama_enabled
        self._http_client: Optional[httpx.AsyncClient] = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._http_client is None or self._http_client.is_closed:
            self._http_client = httpx.AsyncClient(
                base_url=self.base_url,
                timeout=self.timeout,
            )
        return self._http_client

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

    async def analyze_query(self, query: str) -> Optional[OllamaQueryAnalysis]:
        """Translate unstructured query to Czech search terms, extract category and labels."""
        if not self.enabled:
            return None

        prompt = f"""You are an expert bilingual grocery assistant for Prague supermarkets.
Analyze the user grocery search query: '{query.strip()}'.
Return ONLY a valid JSON object matching this schema:
{{
  "query_cs": "standard Czech supermarket search keyword",
  "category": "category name (e.g. dairy, bakery, produce, beverages, meat)",
  "labels": ["relevant", "descriptive", "tags"],
  "synonyms": ["czech synonym 1", "czech synonym 2"]
}}"""

        try:
            client = await self._get_client()
            payload = {
                "model": self.model,
                "prompt": prompt,
                "format": "json",
                "stream": False,
            }
            resp = await client.post("/api/generate", json=payload)
            if resp.status_code == 200:
                raw_response = resp.json().get("response", "{}")
                data = json.loads(raw_response)
                if data.get("query_cs"):
                    return OllamaQueryAnalysis.model_validate(data)
        except Exception as exc:
            logger.debug(f"Ollama query analysis skipped or timed out: {exc}")

        return None

    async def filter_relevant_indices(self, query: str, titles: List[str]) -> Optional[List[int]]:
        """Ask LLM which candidate product titles are directly relevant to the user query."""
        if not self.enabled or not titles:
            return None

        items_str = "\n".join(f"{i}: {title}" for i, title in enumerate(titles))
        prompt = f"""User grocery search query: "{query}"
Candidate products:
{items_str}

Which product indices are directly relevant to what the user asked for?
Exclude unrelated fallback items from different categories.
Return ONLY valid JSON in format: {{"relevant_indices": [0, 1]}}"""

        try:
            client = await self._get_client()
            payload = {
                "model": self.model,
                "prompt": prompt,
                "format": "json",
                "stream": False,
            }
            resp = await client.post("/api/generate", json=payload)
            if resp.status_code == 200:
                raw_response = resp.json().get("response", "{}")
                data = json.loads(raw_response)
                indices = data.get("relevant_indices")
                if isinstance(indices, list):
                    return [int(i) for i in indices if isinstance(i, (int, str)) and str(i).isdigit() and int(i) < len(titles)]
        except Exception as exc:
            logger.debug(f"Ollama candidate filtering skipped: {exc}")

        return None

    async def close(self) -> None:
        """Close connection pool."""
        if self._http_client and not self._http_client.is_closed:
            await self._http_client.aclose()
