from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
import pytest
from fastmcp import Client
from httpx import ASGITransport, AsyncClient

from app.a2a_agent import GroceryMCPAgent
from app.main import app, mcp_server


@pytest.mark.asyncio
async def test_fastmcp_exposes_api_v1_tools() -> None:
    """FastMCP server should expose /api/v1/* endpoints as MCP tools and exclude UI routes."""
    async with Client(mcp_server) as client:
        tools = await client.list_tools()
        tool_names = [t.name for t in tools]
        assert len(tool_names) >= 8
        assert any("analytics" in name for name in tool_names)
        assert any("staples" in name for name in tool_names)


@pytest.mark.asyncio
async def test_a2a_agent_card_and_send_message_endpoint() -> None:
    """A2A AgentCard and JSON-RPC SendMessage endpoint should work end-to-end."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        card_resp = await ac.get("/.well-known/agent-card.json")
        assert card_resp.status_code == 200
        card = card_resp.json()
        assert card["name"] == "GroceryPlannerAgent"
        assert len(card["skills"]) >= 2

        # SendMessage when no Gemini key is set returns helpful config message via A2A Task
        rpc_resp = await ac.post(
            "/a2a",
            headers={"A2A-Version": "1.0"},
            json={
                "jsonrpc": "2.0",
                "id": "req-1",
                "method": "SendMessage",
                "params": {
                    "message": {
                        "messageId": "msg-1",
                        "role": "ROLE_USER",
                        "parts": [{"text": "Compare butter prices"}],
                    }
                },
            },
        )
        assert rpc_resp.status_code == 200
        body = rpc_resp.json()
        assert "result" in body


@pytest.mark.asyncio
async def test_grocery_mcp_agent_executes_mcp_tool_with_gemini() -> None:
    """GroceryMCPAgent should call FastMCP tools requested by Gemini 3.5 Flash."""
    async with Client(mcp_server) as client:
        tools = await client.list_tools()
        analytics_tool = next(t.name for t in tools if "get_category_analytics" in t.name)

    fc = SimpleNamespace(name=analytics_tool, args={"mode": "comparison"})
    usage_1 = SimpleNamespace(prompt_token_count=100, candidates_token_count=20, cached_content_token_count=0, thoughts_token_count=0, total_token_count=120)
    usage_2 = SimpleNamespace(prompt_token_count=200, candidates_token_count=40, cached_content_token_count=50, thoughts_token_count=10, total_token_count=250)
    first_resp = SimpleNamespace(
        function_calls=[fc],
        candidates=[SimpleNamespace(content=MagicMock())],
        text=None,
        usage_metadata=usage_1,
    )
    final_resp = SimpleNamespace(
        function_calls=[],
        candidates=[],
        text="In comparison mode, Rohlík averages 214.21 CZK and Košík 186.08 CZK.",
        usage_metadata=usage_2,
    )

    mock_genai = MagicMock()
    mock_genai.aio.models.generate_content = AsyncMock(side_effect=[first_resp, final_resp])

    mock_monitoring = MagicMock()
    mock_span = MagicMock()
    mock_monitoring.trace_observation.return_value.__enter__ = MagicMock(return_value=mock_span)
    mock_monitoring.trace_observation.return_value.__exit__ = MagicMock(return_value=False)
    mock_monitoring.trace_generation.return_value.__enter__ = MagicMock(return_value=mock_span)
    mock_monitoring.trace_generation.return_value.__exit__ = MagicMock(return_value=False)

    with patch("app.services.llm.genai.Client", return_value=mock_genai):
        agent = GroceryMCPAgent(
            mcp_target=mcp_server,
            api_key="test-key",
            model="gemini-3.5-flash",
            monitoring=mock_monitoring,
        )
        answer = await agent.run("Compare category averages", context_id="ctx-test")
        assert "214.21" in answer
        assert mock_genai.aio.models.generate_content.call_count == 2
        assert mock_genai.aio.models.generate_content.call_args_list[0].kwargs["model"] == "gemini-3.5-flash"
        assert mock_monitoring.trace_generation.call_count == 2
        gen_updates = [c.kwargs for c in mock_span.update.call_args_list if "cost_details" in c.kwargs]
        assert len(gen_updates) == 2
        assert gen_updates[0]["usage_details"]["total"] == 120
        assert gen_updates[1]["cost_details"]["total"] > 0


def test_create_llm_service_switches_providers() -> None:
    """create_llm_service factory should return OllamaLLMService or GeminiLLMService."""
    from app.services.llm import GeminiLLMService, OllamaLLMService, create_llm_service

    assert isinstance(create_llm_service("ollama"), OllamaLLMService)
    assert isinstance(create_llm_service("gemini"), GeminiLLMService)


@pytest.mark.asyncio
async def test_security_headers_and_optional_api_auth(monkeypatch: pytest.MonkeyPatch) -> None:
    """Middleware must set security headers and enforce API_AUTH_TOKEN on admin endpoints when configured."""
    from app.core.config import settings

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        resp = await ac.get("/.well-known/agent-card.json")
        assert resp.headers.get("X-Content-Type-Options") == "nosniff"
        assert resp.headers.get("X-Frame-Options") == "DENY"
        assert "default-src 'self'" in (resp.headers.get("Content-Security-Policy") or "")

        monkeypatch.setattr(settings, "api_auth_token", "secret-token-123")
        unauth = await ac.post("/api/v1/history/run")
        assert unauth.status_code == 401
        bad = await ac.post("/api/v1/history/run", headers={"X-API-Key": "wrong"})
        assert bad.status_code == 401
