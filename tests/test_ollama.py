import pytest
from unittest.mock import AsyncMock, patch
import httpx
from app.services.ollama import OllamaQueryAnalysis, OllamaService


@pytest.mark.asyncio
async def test_ollama_health_check_success() -> None:
    service = OllamaService(enabled=True)
    with patch.object(service, "_get_client") as mock_get_client:
        mock_client = AsyncMock()
        mock_client.get.return_value = httpx.Response(200, json={"models": []})
        mock_get_client.return_value = mock_client

        healthy = await service.health_check()
        assert healthy is True


@pytest.mark.asyncio
async def test_ollama_health_check_disabled() -> None:
    service = OllamaService(enabled=False)
    assert await service.health_check() is False


@pytest.mark.asyncio
async def test_ollama_analyze_query_enforces_language_metadata_and_disables_thinking() -> None:
    service = OllamaService(enabled=True, think=False)
    mock_payload = {
        "response": (
            '```json\n'
            '{"source_language": "en", '
            '"translations": {"en": "sourdough bread", "cs": "kváskový chléb"}, '
            '"category": "bakery", '
            '"labels": {"en": ["sourdough", "artisan"], "cs": ["kváskový", "řemeslný"]}, '
            '"synonyms": {"en": ["artisan bread"], "cs": ["kváskový chleba"]}, '
            '"is_compound": true}\n'
            '```'
        ),
        "prompt_eval_count": 42,
        "eval_count": 28,
    }

    with patch.object(service, "_get_client") as mock_get_client:
        mock_client = AsyncMock()
        mock_client.post.return_value = httpx.Response(200, json=mock_payload)
        mock_get_client.return_value = mock_client

        analysis = await service.analyze_query("organic sourdough bread")
        assert analysis is not None
        assert isinstance(analysis, OllamaQueryAnalysis)
        assert analysis.source_language == "en"
        assert analysis.query_cs == "kváskový chléb"
        assert analysis.get_translation("en") == "sourdough bread"
        assert analysis.category == "bakery"
        assert analysis.labels["en"] == ["sourdough", "artisan"]
        assert analysis.labels["cs"] == ["kváskový", "řemeslný"]
        assert analysis.is_compound is True

        # Verify think=False was sent in payload and format=json was omitted
        sent_json = mock_client.post.call_args.kwargs["json"]
        assert sent_json["think"] is False
        assert "format" not in sent_json


@pytest.mark.asyncio
async def test_ollama_filter_relevant_indices() -> None:
    service = OllamaService(enabled=True, think=False)
    mock_payload = {"response": '{"relevant_indices": [0, 1]}'}

    with patch.object(service, "_get_client") as mock_get_client:
        mock_client = AsyncMock()
        mock_client.post.return_value = httpx.Response(200, json=mock_payload)
        mock_get_client.return_value = mock_client

        titles = ["Banán 1 ks", "BIO banán 1 ks", "Kiwi, 1 ks", "Mango malé, 1 ks"]
        indices = await service.filter_relevant_indices("bananas", titles)
        assert indices == [0, 1]


@pytest.mark.asyncio
async def test_ollama_graceful_error_handling() -> None:
    service = OllamaService(enabled=True)

    with patch.object(service, "_get_client") as mock_get_client:
        mock_client = AsyncMock()
        mock_client.post.side_effect = httpx.ConnectError("Connection refused")
        mock_get_client.return_value = mock_client

        analysis = await service.analyze_query("anything")
        assert analysis is None

        indices = await service.filter_relevant_indices("anything", ["prod 1"])
        assert indices is None


@pytest.mark.asyncio
async def test_comparator_uses_llm_to_exclude_flavored_derivatives() -> None:
    """Ensure PriceComparisonService uses Ollama filter_relevant_indices to reject kefir/skyr for blueberries."""
    from decimal import Decimal
    from unittest.mock import MagicMock
    from app.models.enums import StoreType, UnitType
    from app.models.product import StoreProduct
    from app.services.comparator import PriceComparisonService

    r_prods = [
        StoreProduct(store=StoreType.ROHLIK, product_id="r1", name="Activia Kefír borůvka", price=Decimal("31.40"), unit_type=UnitType.KILOGRAM, unit_price=Decimal("112.14"), in_stock=True),
        StoreProduct(store=StoreType.ROHLIK, product_id="r2", name="Čerstvé borůvky 250g", price=Decimal("89.90"), unit_type=UnitType.KILOGRAM, unit_price=Decimal("359.60"), in_stock=True),
    ]
    k_prods = [
        StoreProduct(store=StoreType.KOSIK, product_id="k1", name="Bohušovická mlékárna Skyr tradiční islandský výrobek borůvka (0,1%)", price=Decimal("20.90"), unit_type=UnitType.KILOGRAM, unit_price=Decimal("160.77"), in_stock=True),
    ]

    mock_rohlik = MagicMock()
    mock_rohlik.search = AsyncMock(return_value=r_prods)
    mock_kosik = MagicMock()
    mock_kosik.search = AsyncMock(return_value=k_prods)

    mock_ollama = MagicMock()
    mock_ollama.enabled = True
    mock_ollama.monitoring = None
    mock_ollama.analyze_query = AsyncMock(return_value=None)
    # Rohlík keeps only index 1 (Čerstvé borůvky); Košík rejects index 0 (Skyr borůvka) -> []
    mock_ollama.filter_relevant_indices = AsyncMock(side_effect=[[1], []])

    comp = PriceComparisonService(
        rohlik_client=mock_rohlik,
        kosik_client=mock_kosik,
        ollama_service=mock_ollama,
    )
    res = await comp.compare_single_item("blueberries")
    assert res.primary_pair is not None
    assert res.primary_pair.rohlik_product is not None
    assert res.primary_pair.rohlik_product.name == "Čerstvé borůvky 250g"
    assert res.primary_pair.kosik_product is None


@pytest.mark.asyncio
async def test_ollama_semaphore_serializes_concurrent_calls() -> None:
    """Ensure OllamaService queues concurrent requests via Semaphore(1)."""
    import asyncio

    service = OllamaService(enabled=True, think=False, max_concurrency=1)
    active = 0
    max_active = 0

    async def fake_post(*args: object, **kwargs: object) -> httpx.Response:
        nonlocal active, max_active
        active += 1
        max_active = max(max_active, active)
        await asyncio.sleep(0.02)
        active -= 1
        return httpx.Response(200, json={"response": '{"relevant_indices": [0]}'})

    with patch.object(service, "_get_client") as mock_get_client:
        mock_client = AsyncMock()
        mock_client.post.side_effect = fake_post
        mock_get_client.return_value = mock_client

        results = await asyncio.gather(
            service.filter_relevant_indices("a", ["x"]),
            service.filter_relevant_indices("b", ["y"]),
            service.filter_relevant_indices("c", ["z"]),
        )
        assert results == [[0], [0], [0]]
        assert max_active == 1


@pytest.mark.asyncio
async def test_ollama_caches_identical_prompts() -> None:
    """Identical prompts must return cached results without making a second API call."""
    service = OllamaService(enabled=True, think=False)
    mock_payload = {"response": '{"relevant_indices": [0]}'}

    with patch.object(service, "_get_client") as mock_get_client:
        mock_client = AsyncMock()
        mock_client.post.return_value = httpx.Response(200, json=mock_payload)
        mock_get_client.return_value = mock_client

        first = await service.filter_relevant_indices("blueberries", ["Čerstvé borůvky", "Kefír"], query_cs="borůvky")
        second = await service.filter_relevant_indices("blueberries", ["Čerstvé borůvky", "Kefír"], query_cs="borůvky")

        assert first == [0]
        assert second == [0]
        assert mock_client.post.call_count == 1


@pytest.mark.asyncio
async def test_gemini_filter_relevant_indices_disables_thinking() -> None:
    """Gemini relevance filtering must disable thinking tokens so JSON output is not truncated."""
    from types import SimpleNamespace
    from app.services.llm import GeminiLLMService

    service = GeminiLLMService(api_key="test-key", model="gemini-3.5-flash", enabled=True)
    fake_resp = SimpleNamespace(
        text='{"relevant_indices": [0]}',
        function_calls=[],
        candidates=[],
        usage_metadata=SimpleNamespace(
            prompt_token_count=20,
            candidates_token_count=10,
            cached_content_token_count=0,
            thoughts_token_count=0,
            total_token_count=30,
        ),
    )

    with patch("app.services.llm.genai.Client") as mock_client_cls:
        mock_client = mock_client_cls.return_value
        mock_client.aio.models.generate_content = AsyncMock(return_value=fake_resp)

        indices = await service.filter_relevant_indices(
            "blueberries",
            ["Borůvky, balení", "Activia Kefír borůvka", "Miil Krémový jogurt borůvkový"],
            query_cs="borůvky",
        )

        assert indices == [0]
        call_cfg = mock_client.aio.models.generate_content.call_args.kwargs["config"]
        assert call_cfg.thinking_config is not None
        assert call_cfg.thinking_config.thinking_budget == 0
        assert call_cfg.max_output_tokens >= 256
