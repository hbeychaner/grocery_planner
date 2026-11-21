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
