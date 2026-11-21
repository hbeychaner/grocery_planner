from typing import Generator
from fastapi import Request
from app.clients.base import BaseStoreClient
from app.clients.rohlik import RohlikStoreClient
from app.clients.kosik import KosikStoreClient
from app.services.bilingual import BilingualQueryService
from app.services.comparator import PriceComparisonService
from app.services.matcher import ProductMatchingService
from app.services.ollama import OllamaService
from app.services.voice_formatter import VoiceResponseFormatter


# Singleton store clients for lifetime of app
_rohlik_client = RohlikStoreClient()
_kosik_client = KosikStoreClient()
_bilingual_service = BilingualQueryService()
_matcher_service = ProductMatchingService()
_voice_formatter = VoiceResponseFormatter()
_ollama_service = OllamaService()
_comparator_service = PriceComparisonService(
    rohlik_client=_rohlik_client,
    kosik_client=_kosik_client,
    bilingual_service=_bilingual_service,
    matching_service=_matcher_service,
    voice_formatter=_voice_formatter,
    ollama_service=_ollama_service,
)


def get_comparison_service() -> PriceComparisonService:
    """Dependency provider for PriceComparisonService."""
    return _comparator_service


def get_ollama_service() -> OllamaService:
    """Dependency provider for OllamaService."""
    return _ollama_service


def get_rohlik_client() -> BaseStoreClient:
    """Dependency provider for Rohlik client."""
    return _rohlik_client


def get_kosik_client() -> BaseStoreClient:
    """Dependency provider for Kosik client."""
    return _kosik_client
