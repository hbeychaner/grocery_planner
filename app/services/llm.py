"""Unified LLM service abstraction supporting local Ollama and Google Gemini."""

from __future__ import annotations

from abc import ABC, abstractmethod
import asyncio
from collections import OrderedDict
import hashlib
import json
import logging
import os
import re
from typing import Any, Dict, List, Literal, Optional

import httpx
from google import genai
from google.genai import types as genai_types
from pydantic import BaseModel, Field, field_validator

from app.core.config import settings
from app.services.monitoring import MonitoringService

logger = logging.getLogger(__name__)

LLMProvider = Literal["ollama", "gemini"]

_GEMINI_PRICING_PER_1M: Dict[str, Dict[str, float]] = {
    "gemini-3.5-flash": {"input": 0.30, "cached_input": 0.075, "output": 2.50},
    "gemini-2.5-flash": {"input": 0.30, "cached_input": 0.075, "output": 2.50},
    "gemini-2.0-flash": {"input": 0.10, "cached_input": 0.025, "output": 0.40},
}


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


class LLMFunctionCall(BaseModel):
    """Normalized tool/function call emitted by an LLM."""

    name: str
    args: Dict[str, Any] = Field(default_factory=dict)


class LLMResponse(BaseModel):
    """Normalized response across Ollama and Gemini providers."""

    text: Optional[str] = None
    function_calls: List[LLMFunctionCall] = Field(default_factory=list)
    raw_content: Any = None
    input_tokens: int = 0
    output_tokens: int = 0
    cached_tokens: int = 0
    thoughts_tokens: int = 0
    total_tokens: int = 0
    cost_usd: Dict[str, float] = Field(default_factory=lambda: {"input": 0.0, "output": 0.0, "total": 0.0})


def _clean_json_schema(schema: Any) -> Any:
    """Strip JSON Schema keys not accepted by Gemini FunctionDeclaration."""
    if isinstance(schema, dict):
        return {
            k: _clean_json_schema(v)
            for k, v in schema.items()
            if k not in ("$schema", "additionalProperties", "title", "default")
        }
    if isinstance(schema, list):
        return [_clean_json_schema(item) for item in schema]
    return schema


def compute_gemini_cost(
    model: str,
    input_tokens: int,
    output_tokens: int,
    cached_tokens: int = 0,
    thoughts_tokens: int = 0,
) -> Dict[str, float]:
    """Calculate USD cost breakdown for a Gemini generation."""
    rates = _GEMINI_PRICING_PER_1M.get(model, _GEMINI_PRICING_PER_1M["gemini-3.5-flash"])
    billable_input = max(0, input_tokens - cached_tokens)
    in_cost = (billable_input * rates["input"] + cached_tokens * rates["cached_input"]) / 1_000_000.0
    out_cost = ((output_tokens + thoughts_tokens) * rates["output"]) / 1_000_000.0
    return {
        "input": round(in_cost, 8),
        "output": round(out_cost, 8),
        "total": round(in_cost + out_cost, 8),
    }


class BaseLLMService(ABC):
    """Abstract base class for LLM providers with prompt caching and Langfuse tracing."""

    provider_name: str = "base"

    def __init__(
        self,
        model: str,
        enabled: bool = True,
        monitoring: Optional[MonitoringService] = None,
        cache_max_size: int = 2048,
    ) -> None:
        self.model = model
        self.enabled = enabled
        self.monitoring = monitoring or MonitoringService()
        self._prompt_cache: OrderedDict[str, Any] = OrderedDict()
        self._cache_max_size = cache_max_size

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

    def _cache_get(self, key: str) -> Optional[Any]:
        if key in self._prompt_cache:
            self._prompt_cache.move_to_end(key)
            return self._prompt_cache[key]
        return None

    def _cache_set(self, key: str, value: Any) -> None:
        self._prompt_cache[key] = value
        if len(self._prompt_cache) > self._cache_max_size:
            self._prompt_cache.popitem(last=False)

    @abstractmethod
    async def health_check(self) -> bool:
        """Return True if the LLM backend is reachable and configured."""

    @abstractmethod
    async def generate(
        self,
        messages: List[Dict[str, Any]],
        *,
        system_instruction: Optional[str] = None,
        tools: Optional[List[Dict[str, Any]]] = None,
        temperature: float = 0.2,
        max_tokens: int = 512,
    ) -> Optional[LLMResponse]:
        """Execute a chat/generation turn with optional tool definitions."""

    async def close(self) -> None:
        """Optional resource cleanup hook."""
        return None

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

        model_params = {"num_predict": 256, "temperature": 0.1}
        with self.monitoring.trace_generation(
            name="translate-and-classify-query",
            model=self.model,
            input_data=[{"role": "user", "content": prompt}],
            metadata={"query": query, "target_languages": langs, "provider": self.provider_name},
            model_parameters=model_params,
        ) as span:
            try:
                resp = await self.generate(
                    [{"role": "user", "content": prompt}],
                    temperature=0.1,
                    max_tokens=256,
                )
                if resp and resp.text:
                    data = self._extract_json(resp.text)
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
                                output={"role": "assistant", "content": resp.text},
                                metadata={"parsed": analysis.model_dump()},
                                usage_details={"input": resp.input_tokens, "output": resp.output_tokens},
                                cost_details=resp.cost_usd,
                            )
                        return analysis
            except Exception as exc:
                logger.debug(f"{self.provider_name} query analysis skipped or failed: {exc}")
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
        query_label = (
            f'"{query}" (Czech: "{query_cs}")'
            if query_cs and query_cs.lower() != query.lower()
            else f'"{query}"'
        )
        prompt = f"""Requested grocery item: {query_label}
Candidate products:
{items_str}

Select the indices of products that ARE the requested grocery or household item (including normal varieties, brands, scents, sliced/grated forms, or regional/PDO names like Parmigiano Reggiano for parmesan, or anti-dandruff/volume shampoo for shampoo).
ONLY EXCLUDE products from a DIFFERENT product category that merely use the item as a flavor or minor ingredient:
- e.g. for "blueberries" / "borůvky": include fresh or frozen blueberries, EXCLUDE blueberry kefir, skyr, yogurt, jam, tea, or juice.
- e.g. for "butter" / "máslo": include dairy butter, EXCLUDE butter cookies, peanut butter, or cocoa butter.
- e.g. for "chicken breast" / "kuřecí prsa": include chicken breast meat, EXCLUDE chicken broth, soup, or pet food.
- e.g. for "juicing oranges" / "pomeranče na šťávu": include fresh oranges, EXCLUDE bottled orange juice.
Return ONLY valid JSON: {{"relevant_indices": [0, 1]}}"""

        model_params = {"num_predict": 128, "temperature": 0.0}
        with self.monitoring.trace_generation(
            name="filter-relevant-candidates",
            model=self.model,
            input_data=[{"role": "user", "content": prompt}],
            metadata={"query": query, "query_cs": query_cs, "candidate_count": len(titles), "provider": self.provider_name},
            model_parameters=model_params,
        ) as span:
            try:
                resp = await self.generate(
                    [{"role": "user", "content": prompt}],
                    temperature=0.0,
                    max_tokens=128,
                )
                if resp and resp.text:
                    data = self._extract_json(resp.text)
                    indices = data.get("relevant_indices")
                    if isinstance(indices, list):
                        valid = [
                            int(i)
                            for i in indices
                            if isinstance(i, (int, str)) and str(i).isdigit() and 0 <= int(i) < len(titles)
                        ]
                        if span is not None:
                            span.update(
                                output={"role": "assistant", "content": resp.text},
                                metadata={"relevant_indices": valid},
                                usage_details={"input": resp.input_tokens, "output": resp.output_tokens},
                                cost_details=resp.cost_usd,
                            )
                        return valid
            except Exception as exc:
                logger.debug(f"{self.provider_name} candidate filtering skipped: {exc}")
                if span is not None:
                    span.update(level="WARNING", status_message=str(exc))

        return None


class OllamaLLMService(BaseLLMService):
    """Local Ollama LLM provider with per-loop Semaphore queueing and prompt caching."""

    provider_name = "ollama"

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
        super().__init__(
            model=model or settings.ollama_model,
            enabled=enabled if enabled is not None else settings.ollama_enabled,
            monitoring=monitoring,
        )
        self.base_url = (base_url or settings.ollama_base_url).rstrip("/")
        self.timeout = timeout or settings.ollama_timeout_seconds
        self.think = think if think is not None else settings.ollama_think
        self.max_concurrency = max(
            1, max_concurrency if max_concurrency is not None else settings.ollama_max_concurrency
        )
        self._http_client: Optional[httpx.AsyncClient] = None
        self._semaphore: Optional[asyncio.Semaphore] = None
        self._semaphore_loop: Optional[asyncio.AbstractEventLoop] = None

    def _get_semaphore(self) -> asyncio.Semaphore:
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

    async def health_check(self) -> bool:
        if not self.enabled:
            return False
        try:
            client = await self._get_client()
            resp = await client.get("/api/tags")
            return resp.status_code == 200
        except Exception:
            return False

    async def _post_generate(self, payload: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Call Ollama /api/generate with exact-prompt caching and Semaphore queueing."""
        cache_key = hashlib.sha256(
            f"{payload.get('model')}|{payload.get('think')}|{payload.get('prompt', '')}".encode("utf-8")
        ).hexdigest()
        cached = self._cache_get(cache_key)
        if cached is not None:
            return cached  # type: ignore[no-any-return]

        client = await self._get_client()
        async with self._get_semaphore():
            cached = self._cache_get(cache_key)
            if cached is not None:
                return cached  # type: ignore[no-any-return]
            resp = await client.post("/api/generate", json=payload)
            if resp.status_code != 200:
                return None
            body: Dict[str, Any] = resp.json()
            self._cache_set(cache_key, body)
            return body

    async def generate(
        self,
        messages: List[Dict[str, Any]],
        *,
        system_instruction: Optional[str] = None,
        tools: Optional[List[Dict[str, Any]]] = None,
        temperature: float = 0.2,
        max_tokens: int = 512,
    ) -> Optional[LLMResponse]:
        if not self.enabled:
            return None

        # Single-turn prompt without tools uses /api/generate (preserves existing test mocks & prompt cache)
        if len(messages) == 1 and not tools and not system_instruction:
            payload: Dict[str, Any] = {
                "model": self.model,
                "prompt": str(messages[0].get("content", "")),
                "think": self.think,
                "stream": False,
                "options": {"num_predict": max_tokens, "temperature": temperature},
            }
            body = await self._post_generate(payload)
            if body is None:
                return None
            in_tok = int(body.get("prompt_eval_count", 0))
            out_tok = int(body.get("eval_count", 0))
            return LLMResponse(
                text=body.get("response", ""),
                input_tokens=in_tok,
                output_tokens=out_tok,
                total_tokens=in_tok + out_tok,
            )

        # Multi-turn or tool-calling uses Ollama /api/chat
        chat_messages: List[Dict[str, Any]] = []
        if system_instruction:
            chat_messages.append({"role": "system", "content": system_instruction})
        for m in messages:
            if m.get("_raw_ollama"):
                chat_messages.append(m["_raw_ollama"])
            else:
                chat_messages.append({"role": m.get("role", "user"), "content": m.get("content", "")})

        chat_payload: Dict[str, Any] = {
            "model": self.model,
            "messages": chat_messages,
            "think": self.think,
            "stream": False,
            "options": {"num_predict": max_tokens, "temperature": temperature},
        }
        if tools:
            chat_payload["tools"] = [
                {
                    "type": "function",
                    "function": {
                        "name": t["name"],
                        "description": t.get("description", ""),
                        "parameters": t.get("parameters", {"type": "object", "properties": {}}),
                    },
                }
                for t in tools
            ]

        client = await self._get_client()
        async with self._get_semaphore():
            resp = await client.post("/api/chat", json=chat_payload)
        if resp.status_code != 200:
            return None
        body = resp.json()
        msg_obj = body.get("message", {}) or {}
        tool_calls = [
            LLMFunctionCall(
                name=tc.get("function", {}).get("name", ""),
                args=tc.get("function", {}).get("arguments", {}) or {},
            )
            for tc in (msg_obj.get("tool_calls") or [])
        ]
        in_tok = int(body.get("prompt_eval_count", 0))
        out_tok = int(body.get("eval_count", 0))
        return LLMResponse(
            text=msg_obj.get("content") or "",
            function_calls=tool_calls,
            raw_content={"_raw_ollama": msg_obj},
            input_tokens=in_tok,
            output_tokens=out_tok,
            total_tokens=in_tok + out_tok,
        )

    async def close(self) -> None:
        if self._http_client and not self._http_client.is_closed:
            await self._http_client.aclose()


class GeminiLLMService(BaseLLMService):
    """Google Gemini LLM provider (e.g. gemini-3.5-flash) with USD cost tracking."""

    provider_name = "gemini"

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: Optional[str] = None,
        enabled: bool = True,
        monitoring: Optional[MonitoringService] = None,
    ) -> None:
        super().__init__(
            model=model or settings.gemini_model,
            enabled=enabled,
            monitoring=monitoring,
        )
        self.api_key = (
            api_key
            or settings.gemini_api_key
            or os.getenv("GEMINI_API_KEY")
            or os.getenv("GOOGLE_API_KEY")
        )

    async def health_check(self) -> bool:
        return bool(self.enabled and self.api_key)

    async def generate(
        self,
        messages: List[Dict[str, Any]],
        *,
        system_instruction: Optional[str] = None,
        tools: Optional[List[Dict[str, Any]]] = None,
        temperature: float = 0.2,
        max_tokens: int = 1024,
    ) -> Optional[LLMResponse]:
        if not self.enabled or not self.api_key:
            return None

        # Exact-prompt cache for stateless single-turn non-tool calls
        cache_key: Optional[str] = None
        if len(messages) == 1 and not tools:
            cache_key = hashlib.sha256(
                f"gemini|{self.model}|{system_instruction}|{temperature}|{messages[0].get('content', '')}".encode("utf-8")
            ).hexdigest()
            cached = self._cache_get(cache_key)
            if cached is not None:
                return cached  # type: ignore[no-any-return]

        declarations = [
            genai_types.FunctionDeclaration(
                name=t["name"],
                description=(t.get("description") or t["name"])[:512],
                parameters_json_schema=_clean_json_schema(
                    t.get("parameters") or {"type": "object", "properties": {}}
                ),
            )
            for t in (tools or [])
        ]
        config = genai_types.GenerateContentConfig(
            system_instruction=system_instruction,
            tools=[genai_types.Tool(function_declarations=declarations)] if declarations else None,
            temperature=temperature,
            max_output_tokens=max_tokens,
        )

        contents: List[genai_types.Content] = []
        for m in messages:
            if m.get("_raw_gemini") is not None:
                contents.append(m["_raw_gemini"])
            elif m.get("role") == "tool_results":
                parts = [
                    genai_types.Part.from_function_response(
                        name=tr["name"],
                        response=tr["response"] if isinstance(tr["response"], dict) else {"result": tr["response"]},
                    )
                    for tr in m.get("results", [])
                ]
                contents.append(genai_types.Content(role="user", parts=parts))
            else:
                role = "model" if m.get("role") == "assistant" else "user"
                contents.append(
                    genai_types.Content(
                        role=role,
                        parts=[genai_types.Part.from_text(text=str(m.get("content", "")))],
                    )
                )

        genai_client = genai.Client(api_key=self.api_key)
        response = await genai_client.aio.models.generate_content(
            model=self.model,
            contents=contents,
            config=config,
        )

        usage_meta = getattr(response, "usage_metadata", None)
        in_tok = int(getattr(usage_meta, "prompt_token_count", 0) or 0)
        out_tok = int(getattr(usage_meta, "candidates_token_count", 0) or 0)
        cached_tok = int(getattr(usage_meta, "cached_content_token_count", 0) or 0)
        thought_tok = int(getattr(usage_meta, "thoughts_token_count", 0) or 0)
        tot_tok = int(getattr(usage_meta, "total_token_count", 0) or (in_tok + out_tok + thought_tok))

        fc_list = [
            LLMFunctionCall(name=fc.name or "", args=dict(fc.args) if fc.args else {})
            for fc in (response.function_calls or [])
        ]
        raw_content = (
            {"_raw_gemini": response.candidates[0].content}
            if getattr(response, "candidates", None) and response.candidates[0].content
            else None
        )
        llm_resp = LLMResponse(
            text=response.text or "",
            function_calls=fc_list,
            raw_content=raw_content,
            input_tokens=in_tok,
            output_tokens=out_tok,
            cached_tokens=cached_tok,
            thoughts_tokens=thought_tok,
            total_tokens=tot_tok,
            cost_usd=compute_gemini_cost(self.model, in_tok, out_tok, cached_tok, thought_tok),
        )
        if cache_key is not None:
            self._cache_set(cache_key, llm_resp)
        return llm_resp


def create_llm_service(
    provider: Optional[str] = None,
    monitoring: Optional[MonitoringService] = None,
) -> BaseLLMService:
    """Instantiate the configured LLM provider ('ollama' or 'gemini')."""
    selected = (provider or "ollama").strip().lower()
    if selected == "gemini":
        return GeminiLLMService(monitoring=monitoring)
    return OllamaLLMService(monitoring=monitoring)
