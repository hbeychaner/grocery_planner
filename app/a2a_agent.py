"""A2A-compliant Grocery Assistant Agent powered by Gemini 3.5 Flash & FastMCP.

Exposes:
  - ``/.well-known/agent-card.json`` (A2A AgentCard discovery)
  - ``/a2a`` (A2A JSON-RPC 2.0 endpoint, including v0.3 compat)
  - ``/a2a/rest`` (A2A HTTP+JSON REST transport)

The agent discovers tools dynamically from the FastMCP server via ``fastmcp.Client``
and uses Google GenAI (``gemini-3.5-flash``) function calling to execute them.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any, Dict, List, Optional, Union

from a2a.server.agent_execution import AgentExecutor, RequestContext
from a2a.server.events import EventQueue
from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.routes.agent_card_routes import create_agent_card_routes
from a2a.server.routes.fastapi_routes import add_a2a_routes_to_fastapi
from a2a.server.routes.jsonrpc_routes import create_jsonrpc_routes
from a2a.server.routes.rest_routes import create_rest_routes
from a2a.server.tasks import InMemoryTaskStore, TaskUpdater
from a2a.types import (
    AgentCapabilities,
    AgentCard,
    AgentInterface,
    AgentSkill,
    Part,
    Task,
    TaskState,
    TaskStatus,
)
from fastapi import FastAPI
from fastmcp import Client, FastMCP
from fastmcp.client.transports import StreamableHttpTransport
from google import genai
from google.genai import types as genai_types

from app.core.config import settings

logger = logging.getLogger(__name__)

SYSTEM_INSTRUCTION = (
    "You are the Grocery Planner AI assistant for Prague supermarkets (Rohlík.cz and Košík.cz), "
    "with historical Czech (ČSÚ) and US (BLS) price trend analytics. "
    "Always use the available MCP tools to look up live prices, compare baskets, check watchlist items, "
    "or inspect category trends before answering. Be concise, accurate, and cite prices in CZK."
)


def _clean_json_schema(schema: Any) -> Any:
    """Strip JSON Schema keys not accepted by Gemini FunctionDeclaration."""
    if isinstance(schema, dict):
        cleaned: Dict[str, Any] = {}
        for k, v in schema.items():
            if k in ("$schema", "additionalProperties", "title", "default"):
                continue
            cleaned[k] = _clean_json_schema(v)
        return cleaned
    if isinstance(schema, list):
        return [_clean_json_schema(item) for item in schema]
    return schema


class GroceryMCPAgent:
    """Gemini 3.5 Flash agent that discovers and invokes backend tools via FastMCP."""

    def __init__(
        self,
        mcp_target: Union[FastMCP, str],
        api_key: Optional[str] = None,
        model: Optional[str] = None,
    ) -> None:
        self.mcp_target = mcp_target
        self.api_key = api_key or settings.gemini_api_key or os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
        self.model = model or settings.gemini_model

    def _build_mcp_client(self) -> Client:
        if isinstance(self.mcp_target, str):
            return Client(StreamableHttpTransport(url=self.mcp_target))
        return Client(self.mcp_target)

    async def run(self, user_message: str) -> str:
        """Run a multi-turn Gemini 3.5 Flash tool-calling loop over FastMCP tools."""
        if not self.api_key:
            return (
                "Gemini API key is not configured. Please set `GEMINI_API_KEY` in your `.env` "
                "file and restart the server to chat with Gemini 3.5 Flash."
            )

        genai_client = genai.Client(api_key=self.api_key)

        async with self._build_mcp_client() as mcp_client:
            mcp_tools = await mcp_client.list_tools()
            declarations = [
                genai_types.FunctionDeclaration(
                    name=t.name,
                    description=(t.description or t.name)[:512],
                    parameters_json_schema=_clean_json_schema(t.input_schema or {"type": "object", "properties": {}}),
                )
                for t in mcp_tools
            ]
            tool_config = genai_types.GenerateContentConfig(
                system_instruction=SYSTEM_INSTRUCTION,
                tools=[genai_types.Tool(function_declarations=declarations)] if declarations else None,
                temperature=0.2,
            )

            contents: List[genai_types.Content] = [
                genai_types.Content(
                    role="user",
                    parts=[genai_types.Part.from_text(text=user_message)],
                )
            ]

            for _ in range(6):
                response = await genai_client.aio.models.generate_content(
                    model=self.model,
                    contents=contents,
                    config=tool_config,
                )
                if not response.function_calls:
                    return response.text or "I couldn't generate a response."

                # Append model turn with function calls
                if response.candidates and response.candidates[0].content:
                    contents.append(response.candidates[0].content)

                # Execute every requested MCP tool via FastMCP Client
                tool_parts: List[genai_types.Part] = []
                for fc in response.function_calls:
                    tool_name = fc.name or ""
                    tool_args = dict(fc.args) if fc.args else {}
                    try:
                        mcp_result = await mcp_client.call_tool(tool_name, tool_args)
                        text_chunks = [
                            getattr(c, "text", str(c))
                            for c in (mcp_result.content or [])
                        ]
                        raw_output = "\n".join(text_chunks) if text_chunks else "{}"
                        try:
                            parsed_output: Any = json.loads(raw_output)
                        except json.JSONDecodeError:
                            parsed_output = {"result": raw_output}
                    except Exception as exc:
                        logger.warning("MCP tool '%s' failed: %s", tool_name, exc)
                        parsed_output = {"error": str(exc)}

                    tool_parts.append(
                        genai_types.Part.from_function_response(
                            name=tool_name,
                            response=parsed_output if isinstance(parsed_output, dict) else {"result": parsed_output},
                        )
                    )

                contents.append(genai_types.Content(role="user", parts=tool_parts))

            return "Reached maximum tool-calling steps without a final answer."


class GroceryA2AExecutor(AgentExecutor):
    """A2A AgentExecutor bridging A2A tasks to GroceryMCPAgent."""

    def __init__(self, agent: GroceryMCPAgent) -> None:
        self.agent = agent

    async def execute(self, context: RequestContext, event_queue: EventQueue) -> None:
        task_id = context.task_id or "task-unknown"
        context_id = context.context_id or "ctx-default"
        if not context.current_task:
            await event_queue.enqueue_event(
                Task(
                    id=task_id,
                    context_id=context_id,
                    status=TaskStatus(state=TaskState.TASK_STATE_SUBMITTED),
                    history=[context.message] if context.message else [],
                )
            )
        updater = TaskUpdater(
            event_queue=event_queue,
            task_id=task_id,
            context_id=context_id,
        )
        await updater.start_work()
        try:
            user_text = context.get_user_input() or ""
            reply = await self.agent.run(user_text)
            msg = updater.new_agent_message([Part(text=reply)])
            await updater.complete(msg)
        except Exception as exc:
            logger.exception("A2A agent execution failed: %s", exc)
            err_msg = updater.new_agent_message([Part(text=f"Agent error: {exc}")])
            await updater.failed(err_msg)

    async def cancel(self, context: RequestContext, event_queue: EventQueue) -> None:
        updater = TaskUpdater(
            event_queue=event_queue,
            task_id=context.task_id or "task-unknown",
            context_id=context.context_id or "ctx-default",
        )
        await updater.cancel()


def create_agent_card(base_url: str = "http://localhost:8000") -> AgentCard:
    """Build the A2A AgentCard describing GroceryPlannerAgent."""
    return AgentCard(
        name="GroceryPlannerAgent",
        description="Bilingual Czech/English grocery price comparator and historical trends agent powered by Gemini 3.5 Flash & FastMCP.",
        version="0.1.0",
        supported_interfaces=[
            AgentInterface(protocol_binding="JSONRPC", protocol_version="1.0", url=f"{base_url}/a2a"),
            AgentInterface(protocol_binding="HTTP+JSON", protocol_version="1.0", url=f"{base_url}/a2a/rest"),
        ],
        capabilities=AgentCapabilities(streaming=False, push_notifications=False),
        default_input_modes=["text/plain"],
        default_output_modes=["text/plain"],
        skills=[
            AgentSkill(
                id="compare_groceries",
                name="Compare Grocery Prices",
                description="Compare real-time prices between Rohlík.cz and Košík.cz for single items or full baskets.",
                tags=["groceries", "prague", "rohlik", "kosik"],
                examples=["Compare butter prices between Rohlík and Košík", "Where is whole milk cheaper?"],
            ),
            AgentSkill(
                id="price_trends",
                name="Price Trends & Inflation Analytics",
                description="Query historical ČSÚ, US BLS, Rohlík, and Košík category averages and trends.",
                tags=["analytics", "inflation", "trends"],
                examples=["How have dairy prices changed over time?", "Show comparison analytics for fruits."],
            ),
        ],
    )


def mount_a2a_agent(
    fastapi_app: FastAPI,
    mcp_target: Union[FastMCP, str],
    base_url: Optional[str] = None,
) -> AgentCard:
    """Register A2A AgentCard, JSON-RPC, and REST routes on the FastAPI app."""
    resolved_base = base_url or f"http://localhost:{settings.app_port}"
    agent_card = create_agent_card(base_url=resolved_base)
    agent = GroceryMCPAgent(mcp_target=mcp_target)
    executor = GroceryA2AExecutor(agent=agent)
    request_handler = DefaultRequestHandler(
        agent_executor=executor,
        task_store=InMemoryTaskStore(),
        agent_card=agent_card,
    )
    add_a2a_routes_to_fastapi(
        fastapi_app,
        agent_card_routes=create_agent_card_routes(agent_card),
        jsonrpc_routes=create_jsonrpc_routes(request_handler, rpc_url="/a2a", enable_v0_3_compat=True),
        rest_routes=create_rest_routes(request_handler, path_prefix="/a2a/rest", enable_v0_3_compat=True),
    )
    return agent_card
