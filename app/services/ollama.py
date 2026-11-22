"""Backwards-compatible re-exports for OllamaLLMService."""

from app.services.llm import (
    BaseLLMService,
    GeminiLLMService,
    OllamaLLMService,
    OllamaQueryAnalysis,
    create_llm_service,
)

OllamaService = OllamaLLMService

__all__ = [
    "BaseLLMService",
    "GeminiLLMService",
    "OllamaLLMService",
    "OllamaQueryAnalysis",
    "OllamaService",
    "create_llm_service",
]
