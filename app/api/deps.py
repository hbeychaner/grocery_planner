from app.clients.base import BaseStoreClient
from app.clients.rohlik import RohlikStoreClient
from app.clients.kosik import KosikStoreClient
from app.services.bilingual import BilingualQueryService
from app.services.comparator import PriceComparisonService
from app.services.matcher import ProductMatchingService
from app.services.monitoring import MonitoringService
from app.services.ollama import OllamaService
from app.services.price_history import PriceHistoryService
from app.services.tracker_runner import PriceTrackerRunner
from app.services.translation_cache import TranslationCacheService
from app.services.voice_formatter import VoiceResponseFormatter


# Singleton services for lifetime of app
_rohlik_client = RohlikStoreClient()
_kosik_client = KosikStoreClient()
_monitoring_service = MonitoringService()
_translation_cache = TranslationCacheService()
_bilingual_service = BilingualQueryService(cache_service=_translation_cache)
_matcher_service = ProductMatchingService()
_voice_formatter = VoiceResponseFormatter()
_ollama_service = OllamaService(monitoring=_monitoring_service)
_comparator_service = PriceComparisonService(
    rohlik_client=_rohlik_client,
    kosik_client=_kosik_client,
    bilingual_service=_bilingual_service,
    matching_service=_matcher_service,
    voice_formatter=_voice_formatter,
    ollama_service=_ollama_service,
)
_price_history_service = PriceHistoryService()
_price_history_service.seed_default_items(BilingualQueryService.DICTIONARY)
_tracker_runner = PriceTrackerRunner(
    comparator=_comparator_service,
    history=_price_history_service,
)


def get_comparison_service() -> PriceComparisonService:
    """Dependency provider for PriceComparisonService."""
    return _comparator_service


def get_ollama_service() -> OllamaService:
    """Dependency provider for OllamaService."""
    return _ollama_service


def get_monitoring_service() -> MonitoringService:
    """Dependency provider for MonitoringService."""
    return _monitoring_service


def get_translation_cache() -> TranslationCacheService:
    """Dependency provider for TranslationCacheService."""
    return _translation_cache


def get_rohlik_client() -> BaseStoreClient:
    """Dependency provider for Rohlik client."""
    return _rohlik_client


def get_kosik_client() -> BaseStoreClient:
    """Dependency provider for Kosik client."""
    return _kosik_client


def get_price_history_service() -> PriceHistoryService:
    """Dependency provider for PriceHistoryService."""
    return _price_history_service


def get_tracker_runner() -> PriceTrackerRunner:
    """Dependency provider for PriceTrackerRunner."""
    return _tracker_runner
