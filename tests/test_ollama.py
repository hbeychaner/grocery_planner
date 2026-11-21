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
async def test_ollama_analyze_query() -> None:
    service = OllamaService(enabled=True)
    mock_payload = {
        "response": '{"query_cs": "kváskový chléb", "category": "bakery", "labels": ["organic", "sourdough"], "synonyms": ["kváskový chleba"]}'
    }

    with patch.object(service, "_get_client") as mock_get_client:
        mock_client = AsyncMock()
        mock_client.post.return_value = httpx.Response(200, json=mock_payload)
        mock_get_client.return_value = mock_client

        analysis = await service.analyze_query("organic sourdough bread")
        assert analysis is not None
        assert isinstance(analysis, OllamaQueryAnalysis)
        assert analysis.query_cs == "kváskový chléb"
        assert analysis.category == "bakery"
        assert "sourdough" in analysis.labels


@pytest.mark.asyncio
async def test_ollama_filter_relevant_indices() -> None:
    service = OllamaService(enabled=True)
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
