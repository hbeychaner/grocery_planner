from pathlib import Path
from unittest.mock import AsyncMock
import pytest

from app.services.bilingual import BilingualQueryService
from app.services.ollama import OllamaQueryAnalysis
from app.services.translation_cache import (
    CachedTranslation,
    CompoundKeywordAnalyzer,
    TranslationCacheService,
)
from app.services.voice_formatter import VoiceResponseFormatter


def test_sqlite_translation_cache_roundtrip() -> None:
    cache = TranslationCacheService(db_path=Path(":memory:"))
    record = CachedTranslation(
        normalized_term="sourdough bread",
        source_lang="en",
        target_lang="cs",
        translated_term="kváskový chléb",
        category="bakery",
        labels={"en": ["sourdough"], "cs": ["kváskový"]},
        synonyms={"cs": ["kváskový chleba"]},
        is_compound=True,
        source="ollama",
    )
    cache.upsert(record)

    hit = cache.get("Sourdough  Bread", target_lang="cs")
    assert hit is not None
    assert hit.translated_term == "kváskový chléb"
    assert hit.labels["cs"] == ["kváskový"]
    assert hit.is_compound is True
    assert hit.hit_count == 2
    cache.close()


def test_compound_keyword_analyzer() -> None:
    cache = TranslationCacheService(db_path=Path(":memory:"))
    cache.seed_from_dictionary({"olive oil": ["olivový olej"], "peanut butter": ["arašídové máslo"]})
    analyzer = CompoundKeywordAnalyzer(cache=cache)

    # Cached compound phrase -> single keyword
    res_cached = analyzer.analyze("olive oil")
    assert res_cached.is_single_keyword is True
    assert res_cached.is_compound is True
    assert res_cached.sub_queries == ["olive oil"]

    # Explicit conjunction -> split
    res_split = analyzer.analyze("milk and bread")
    assert res_split.is_single_keyword is False
    assert res_split.sub_queries == ["milk", "bread"]

    # spaCy compound dependency (e.g. "almond butter") -> single keyword
    res_compound = analyzer.analyze("almond butter")
    assert res_compound.is_single_keyword is True
    assert res_compound.is_compound is True
    cache.close()


@pytest.mark.asyncio
async def test_bilingual_uses_sqlite_cache_before_ollama() -> None:
    cache = TranslationCacheService(db_path=Path(":memory:"))
    service = BilingualQueryService(cache_service=cache)

    mock_ollama = AsyncMock()
    mock_ollama.enabled = True
    mock_ollama.analyze_query.return_value = OllamaQueryAnalysis(
        source_language="en",
        translations={"en": "oat milk", "cs": "ovesné mléko"},
        category="dairy",
        labels={"en": ["plant-based"], "cs": ["rostlinné"]},
        synonyms={"cs": ["ovesný nápoj"]},
        is_compound=True,
    )

    # First call hits Ollama and caches in SQLite
    first = await service.translate_query_async("oat milk", ollama_service=mock_ollama)
    assert first.primary_term == "ovesné mléko"
    assert first.from_cache is False
    assert mock_ollama.analyze_query.call_count == 1

    # Second call hits SQLite cache directly without calling Ollama
    second = await service.translate_query_async("oat milk", ollama_service=mock_ollama)
    assert second.primary_term == "ovesné mléko"
    assert second.from_cache is True
    assert mock_ollama.analyze_query.call_count == 1
    cache.close()


def test_voice_formatter_czech_no_english_mixing(
    sample_rohlik_butter,
    sample_kosik_butter,
) -> None:
    from app.models.comparison import MatchedProductPair
    from app.models.enums import PriceAdvantage, StoreType
    from decimal import Decimal

    pair = MatchedProductPair(
        query="butter",
        query_cs="máslo",
        rohlik_product=sample_rohlik_butter,
        kosik_product=sample_kosik_butter,
        advantage=PriceAdvantage.ROHLIK_CHEAPER,
        cheaper_store=StoreType.ROHLIK,
        price_difference=Decimal("28.00"),
        percentage_savings=Decimal("11.7"),
    )
    formatter = VoiceResponseFormatter()
    summaries = formatter.format_by_language(
        pair, translations={"en": "butter", "cs": "máslo"}, fallback_query="butter"
    )
    assert "butter" in summaries["en"].lower()
    assert "butter" not in summaries["cs"].lower()
    assert "máslo" in summaries["cs"].lower()
