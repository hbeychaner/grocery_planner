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
    first_resp = SimpleNamespace(
        function_calls=[fc],
        candidates=[SimpleNamespace(content=MagicMock())],
        text=None,
    )
    final_resp = SimpleNamespace(
        function_calls=[],
        candidates=[],
        text="In comparison mode, Rohlík averages 214.21 CZK and Košík 186.08 CZK.",
    )

    mock_genai = MagicMock()
    mock_genai.aio.models.generate_content = AsyncMock(side_effect=[first_resp, final_resp])

    with patch("app.a2a_agent.genai.Client", return_value=mock_genai):
        agent = GroceryMCPAgent(mcp_target=mcp_server, api_key="test-key", model="gemini-3.5-flash")
        answer = await agent.run("Compare category averages")
        assert "214.21" in answer
        assert mock_genai.aio.models.generate_content.call_count == 2
        assert mock_genai.aio.models.generate_content.call_args_list[0].kwargs["model"] == "gemini-3.5-flash"
