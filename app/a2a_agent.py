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
from typing import Any, AsyncGenerator, Dict, List, Optional, Union

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
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, StreamingResponse
from fastmcp import Client, FastMCP
from pydantic import BaseModel


class ChatStreamRequest(BaseModel):
    """Request payload for streaming grocery assistant chat."""

    message: str
    thread_id: Optional[str] = None
from fastmcp.client.transports import StreamableHttpTransport

from app.core.config import settings
from app.services.llm import (
    BaseLLMService,
    GeminiLLMService,
    create_llm_service,
)
from app.services.monitoring import MonitoringService

logger = logging.getLogger(__name__)

SYSTEM_INSTRUCTION = (
    "You are the Grocery Planner AI assistant for Prague supermarkets (Rohlík.cz and Košík.cz), "
    "with historical Czech (ČSÚ) and US (BLS) price trend analytics. "
    "Always use the available MCP tools to look up live prices, compare baskets, check watchlist items, "
    "or inspect category trends before answering. Be concise, accurate, and cite prices in CZK."
)


class GroceryMCPAgent:
    """A2A agent that discovers and invokes backend tools via FastMCP using BaseLLMService."""

    def __init__(
        self,
        mcp_target: Union[FastMCP, str],
        llm_service: Optional[BaseLLMService] = None,
        api_key: Optional[str] = None,
        model: Optional[str] = None,
        monitoring: Optional[MonitoringService] = None,
    ) -> None:
        self.mcp_target = mcp_target
        self.monitoring = monitoring or MonitoringService()
        if llm_service is not None:
            self.llm = llm_service
        elif api_key is not None or model is not None:
            self.llm = GeminiLLMService(api_key=api_key, model=model, monitoring=self.monitoring)
        else:
            self.llm = create_llm_service(settings.agent_llm_provider, monitoring=self.monitoring)
        self.model = self.llm.model

    def _build_mcp_client(self, obo_token: Optional[str] = None) -> Client:
        if isinstance(self.mcp_target, str):
            return Client(StreamableHttpTransport(url=self.mcp_target, auth=obo_token))
        return Client(self.mcp_target)

    async def run(
        self,
        user_message: str,
        context_id: Optional[str] = None,
        obo_token: Optional[str] = None,
        anon_user_id: Optional[str] = None,
    ) -> str:
        """Run a multi-turn LLM tool-calling loop over FastMCP tools with Langfuse tracing."""
        if not await self.llm.health_check():
            return (
                f"LLM provider '{self.llm.provider_name}' is not configured or reachable. "
                "Please check your `.env` settings (e.g. `GEMINI_API_KEY` or `OLLAMA_BASE_URL`)."
            )

        with self.monitoring.trace_context(
            user_id=anon_user_id,
            session_id=context_id,
            tags=["a2a", "obo"] if obo_token else ["a2a"],
        ):
            with self.monitoring.trace_observation(
                name="a2a-grocery-agent",
                as_type="agent",
                input_data={"message": user_message},
                metadata={
                    "model": self.model,
                    "provider": self.llm.provider_name,
                    "protocol": "a2a-1.0",
                    "context_id": context_id,
                    "obo_authenticated": bool(obo_token),
                },
                flush_on_exit=True,
            ) as root_span:
                reply, stats = await self._run_loop(user_message, obo_token=obo_token)
                if root_span is not None:
                    root_span.update(
                        output={"reply": reply},
                        metadata={
                            "model": self.model,
                            "provider": self.llm.provider_name,
                            "turns": stats["turns"],
                            "tool_calls": stats["tool_calls"],
                            "total_input_tokens": stats["input_tokens"],
                            "total_output_tokens": stats["output_tokens"],
                            "total_cost_usd": round(stats["cost_usd"], 8),
                        },
                    )
                return reply

    async def _run_loop(
        self,
        user_message: str,
        obo_token: Optional[str] = None,
    ) -> tuple[str, Dict[str, Any]]:
        stats: Dict[str, Any] = {"turns": 0, "tool_calls": 0, "input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0}

        async with self._build_mcp_client(obo_token=obo_token) as mcp_client:
            with self.monitoring.trace_observation(
                name="mcp-list-tools",
                as_type="retriever",
                input_data={"target": str(type(self.mcp_target).__name__)},
            ) as tools_span:
                mcp_tools = await mcp_client.list_tools()
                if tools_span is not None:
                    tools_span.update(output={"tool_count": len(mcp_tools), "tools": [t.name for t in mcp_tools]})

            tool_defs = [
                {
                    "name": t.name,
                    "description": t.description or t.name,
                    "parameters": t.input_schema or {"type": "object", "properties": {}},
                }
                for t in mcp_tools
            ]
            messages: List[Dict[str, Any]] = [{"role": "user", "content": user_message}]

            for turn in range(6):
                stats["turns"] = turn + 1
                with self.monitoring.trace_generation(
                    name=f"{self.llm.provider_name}-turn-{turn + 1}",
                    model=self.model,
                    input_data={"turn": turn + 1, "message_count": len(messages), "user_message": user_message if turn == 0 else None},
                    model_parameters={"temperature": 0.2},
                ) as gen_span:
                    llm_resp = await self.llm.generate(
                        messages,
                        system_instruction=SYSTEM_INSTRUCTION,
                        tools=tool_defs or None,
                        temperature=0.2,
                        max_tokens=4096,
                    )
                    if llm_resp is None:
                        return "I couldn't generate a response.", stats

                    stats["input_tokens"] += llm_resp.input_tokens
                    stats["output_tokens"] += llm_resp.output_tokens + llm_resp.thoughts_tokens
                    stats["cost_usd"] += llm_resp.cost_usd.get("total", 0.0)

                    if gen_span is not None:
                        usage_details: Dict[str, int] = {
                            "input": llm_resp.input_tokens,
                            "output": llm_resp.output_tokens,
                            "total": llm_resp.total_tokens,
                        }
                        if llm_resp.cached_tokens:
                            usage_details["input_cache_read"] = llm_resp.cached_tokens
                        if llm_resp.thoughts_tokens:
                            usage_details["output_reasoning"] = llm_resp.thoughts_tokens

                        fc_out = [{"name": fc.name, "args": fc.args} for fc in llm_resp.function_calls]
                        gen_span.update(
                            output={"text": llm_resp.text, "function_calls": fc_out} if fc_out else (llm_resp.text or ""),
                            usage_details=usage_details,
                            cost_details=llm_resp.cost_usd,
                        )

                if not llm_resp.function_calls:
                    return (llm_resp.text or "I couldn't generate a response."), stats

                if llm_resp.raw_content:
                    messages.append(llm_resp.raw_content)

                tool_results: List[Dict[str, Any]] = []
                for fc in llm_resp.function_calls:
                    stats["tool_calls"] += 1
                    with self.monitoring.trace_observation(
                        name=f"mcp-tool:{fc.name}",
                        as_type="tool",
                        input_data=fc.args,
                        metadata={"tool_name": fc.name},
                    ) as tool_span:
                        try:
                            mcp_result = await mcp_client.call_tool(fc.name, fc.args)
                            text_chunks = [
                                getattr(c, "text", str(c))
                                for c in (mcp_result.content or [])
                            ]
                            raw_output = "\n".join(text_chunks) if text_chunks else "{}"
                            try:
                                parsed_output: Any = json.loads(raw_output)
                            except json.JSONDecodeError:
                                parsed_output = {"result": raw_output}
                            if tool_span is not None:
                                tool_span.update(output=parsed_output)
                        except Exception as exc:
                            logger.warning("MCP tool '%s' failed: %s", fc.name, exc)
                            parsed_output = {"error": str(exc)}
                            if tool_span is not None:
                                tool_span.update(level="ERROR", status_message=str(exc), output=parsed_output)

                    tool_results.append({"name": fc.name, "response": parsed_output})

                if self.llm.provider_name == "ollama":
                    for tr in tool_results:
                        messages.append({"role": "tool", "content": json.dumps(tr["response"])})
                else:
                    messages.append({"role": "tool_results", "results": tool_results})

            return "Reached maximum tool-calling steps without a final answer.", stats

    async def stream_events(
        self,
        user_message: str,
        obo_token: Optional[str] = None,
        anon_user_id: Optional[str] = None,
        history: Optional[List[Dict[str, str]]] = None,
        session_id: Optional[str] = None,
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """Stream structured thinking, tool call, tool result, and final answer events."""
        with self.monitoring.trace_context(
            user_id=anon_user_id,
            session_id=session_id,
            tags=["chat-stream", "obo"] if obo_token else ["chat-stream"],
        ):
            with self.monitoring.trace_observation(
                name="a2a-grocery-stream",
                as_type="agent",
                input_data={"message": user_message},
                metadata={"model": self.model, "obo_authenticated": bool(obo_token)},
                flush_on_exit=True,
            ):
                async with self._build_mcp_client(obo_token=obo_token) as mcp_client:
                    mcp_tools = await mcp_client.list_tools()
                    tool_defs = [
                        {
                            "name": t.name,
                            "description": t.description or t.name,
                            "parameters": t.input_schema or {"type": "object", "properties": {}},
                        }
                        for t in mcp_tools
                    ]
                    messages: List[Dict[str, Any]] = []
                    for h in (history or [])[-8:]:
                        role = "assistant" if h.get("role") == "bot" else "user"
                        if h.get("text"):
                            messages.append({"role": role, "content": h["text"]})
                    messages.append({"role": "user", "content": user_message})

                    for turn in range(6):
                        yield {"type": "thinking", "turn": turn + 1}
                        llm_resp = await self.llm.generate(
                            messages,
                            system_instruction=SYSTEM_INSTRUCTION,
                            tools=tool_defs or None,
                            temperature=0.2,
                            max_tokens=4096,
                        )
                        if llm_resp is None:
                            yield {"type": "answer", "text": "I couldn't generate a response."}
                            return

                        if not llm_resp.function_calls:
                            yield {"type": "answer", "text": llm_resp.text or "I couldn't generate a response."}
                            return

                        if llm_resp.text and llm_resp.text.strip():
                            yield {"type": "thought", "turn": turn + 1, "text": llm_resp.text.strip()}

                        if llm_resp.raw_content:
                            messages.append(llm_resp.raw_content)

                        tool_results: List[Dict[str, Any]] = []
                        for fc in llm_resp.function_calls:
                            yield {"type": "tool_call", "turn": turn + 1, "name": fc.name, "args": fc.args}
                            ok = True
                            try:
                                mcp_result = await mcp_client.call_tool(fc.name, fc.args)
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
                                ok = False
                                logger.warning("MCP tool '%s' failed: %s", fc.name, exc)
                                parsed_output = {"error": str(exc)}

                            summary = json.dumps(parsed_output, ensure_ascii=False)
                            if len(summary) > 220:
                                summary = summary[:217] + "..."
                            yield {
                                "type": "tool_result",
                                "turn": turn + 1,
                                "name": fc.name,
                                "ok": ok,
                                "summary": summary,
                            }
                            tool_results.append({"name": fc.name, "response": parsed_output})

                        if self.llm.provider_name == "ollama":
                            for tr in tool_results:
                                messages.append({"role": "tool", "content": json.dumps(tr["response"])})
                        else:
                            messages.append({"role": "tool_results", "results": tool_results})

                    yield {"type": "answer", "text": "Reached maximum tool-calling steps without a final answer."}


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
            final_reply = "I couldn't generate a response."
            async for ev in self.agent.stream_events(user_text):
                ev_type = ev.get("type")
                if ev_type == "thought":
                    await updater.update_status(
                        TaskState.TASK_STATE_WORKING,
                        message=updater.new_agent_message([Part(text=ev.get("text", ""))]),
                    )
                elif ev_type == "tool_call":
                    await updater.update_status(
                        TaskState.TASK_STATE_WORKING,
                        message=updater.new_agent_message(
                            [Part(text=f"Calling tool: {ev.get('name')}")]
                        ),
                    )
                elif ev_type == "answer":
                    final_reply = ev.get("text") or final_reply
            await updater.add_artifact([Part(text=final_reply)], name="response")
            msg = updater.new_agent_message([Part(text=final_reply)])
            await updater.complete(msg)
        except Exception as exc:
            logger.exception("A2A agent execution failed: %s", exc)
            err_msg = updater.new_agent_message(
                [Part(text="An internal error occurred while processing your request.")]
            )
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
        capabilities=AgentCapabilities(streaming=True, push_notifications=False),
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
    from app.api.deps import get_monitoring_service

    resolved_base = base_url or f"http://localhost:{settings.app_port}"
    agent_card = create_agent_card(base_url=resolved_base)
    agent = GroceryMCPAgent(mcp_target=mcp_target, monitoring=get_monitoring_service())
    executor = GroceryA2AExecutor(agent=agent)
    request_handler = DefaultRequestHandler(
        agent_executor=executor,
        task_store=InMemoryTaskStore(),
        agent_card=agent_card,
    )
    from app.api.deps import get_auth_service
    from app.services.auth import anonymize_user_id

    @fastapi_app.get("/api/v1/chat/threads", include_in_schema=False)
    async def list_chat_threads(request: Request) -> JSONResponse:
        auth_svc = get_auth_service()
        user = auth_svc.get_user_by_session(request.cookies.get("gp_session"))
        user_key = user.id if user is not None else (request.client.host if request.client else "anon")
        return JSONResponse({"threads": auth_svc.list_chat_threads(user_key)})

    @fastapi_app.post("/api/v1/chat/threads", include_in_schema=False)
    async def create_chat_thread(request: Request) -> JSONResponse:
        auth_svc = get_auth_service()
        user = auth_svc.get_user_by_session(request.cookies.get("gp_session"))
        user_key = user.id if user is not None else (request.client.host if request.client else "anon")
        return JSONResponse({"thread": auth_svc.create_chat_thread(user_key)})

    @fastapi_app.get("/api/v1/chat/threads/{thread_id}", include_in_schema=False)
    async def get_chat_thread_messages(request: Request, thread_id: str) -> JSONResponse:
        auth_svc = get_auth_service()
        user = auth_svc.get_user_by_session(request.cookies.get("gp_session"))
        user_key = user.id if user is not None else (request.client.host if request.client else "anon")
        msgs = auth_svc.get_chat_messages(user_key, thread_id)
        if msgs is None:
            return JSONResponse(status_code=404, content={"detail": "Chat thread not found"})
        return JSONResponse({"thread_id": thread_id, "messages": msgs})

    @fastapi_app.delete("/api/v1/chat/threads/{thread_id}", include_in_schema=False)
    async def delete_chat_thread(request: Request, thread_id: str) -> JSONResponse:
        auth_svc = get_auth_service()
        user = auth_svc.get_user_by_session(request.cookies.get("gp_session"))
        user_key = user.id if user is not None else (request.client.host if request.client else "anon")
        deleted = auth_svc.delete_chat_thread(user_key, thread_id)
        if not deleted:
            return JSONResponse(status_code=404, content={"detail": "Chat thread not found"})
        return JSONResponse({"deleted": True})

    @fastapi_app.post("/api/v1/chat/stream", include_in_schema=False)
    async def stream_agent_chat(
        request: Request,
        payload: ChatStreamRequest,
    ) -> Any:
        auth_svc = get_auth_service()
        user = auth_svc.get_user_by_session(request.cookies.get("gp_session"))
        user_key = user.id if user is not None else (request.client.host if request.client else "anon")
        allowed, _remaining = auth_svc.consume_daily_chat_quota(user_key)
        if not allowed:
            return JSONResponse(
                status_code=429,
                content={
                    "detail": (
                        f"Daily chat limit reached ({settings.max_chats_per_user_per_day} "
                        "chats per user per day). Please try again tomorrow."
                    )
                },
            )

        thread_id = payload.thread_id
        prior_msgs: Optional[List[Dict[str, Any]]] = None
        if thread_id:
            prior_msgs = auth_svc.get_chat_messages(user_key, thread_id)
        if prior_msgs is None:
            created = auth_svc.create_chat_thread(user_key)
            thread_id = created["id"]
            prior_msgs = []

        auth_svc.append_chat_message(user_key, thread_id, "user", payload.message)
        obo_token = auth_svc.mint_obo_jwt(user.id) if user is not None else auth_svc.mint_obo_jwt(user_key)
        anon_id = anonymize_user_id(user_key)

        async def _event_gen() -> AsyncGenerator[str, None]:
            yield f"data: {json.dumps({'type': 'thread', 'thread_id': thread_id})}\n\n"
            recorded_steps: List[Dict[str, Any]] = []
            try:
                async for ev in agent.stream_events(
                    payload.message,
                    obo_token=obo_token,
                    anon_user_id=anon_id,
                    history=[{"role": m["role"], "text": m["text"]} for m in (prior_msgs or [])],
                    session_id=thread_id,
                ):
                    if ev.get("type") == "thought":
                        recorded_steps.append({"kind": "thought", "label": ev.get("text", ""), "status": "done"})
                    elif ev.get("type") == "tool_call":
                        recorded_steps.append(
                            {
                                "kind": "tool",
                                "label": ev.get("name", ""),
                                "detail": json.dumps(ev.get("args") or {}),
                                "status": "running",
                            }
                        )
                    elif ev.get("type") == "tool_result":
                        for s in reversed(recorded_steps):
                            if s.get("kind") == "tool" and s.get("status") == "running":
                                s["status"] = "done" if ev.get("ok") else "error"
                                s["detail"] = ev.get("summary")
                                break
                    elif ev.get("type") == "answer":
                        auth_svc.append_chat_message(
                            user_key,
                            thread_id,
                            "bot",
                            ev.get("text", ""),
                            steps=recorded_steps,
                        )
                    yield f"data: {json.dumps(ev, ensure_ascii=False)}\n\n"
            except Exception as exc:
                yield f"data: {json.dumps({'type': 'error', 'message': str(exc)})}\n\n"

        return StreamingResponse(
            _event_gen(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    # Register after explicit routes because a2a-sdk mounts a catch-all /{tenant} route.
    add_a2a_routes_to_fastapi(
        fastapi_app,
        agent_card_routes=create_agent_card_routes(agent_card),
        jsonrpc_routes=create_jsonrpc_routes(request_handler, rpc_url="/a2a", enable_v0_3_compat=True),
        rest_routes=create_rest_routes(request_handler, path_prefix="/a2a/rest", enable_v0_3_compat=True),
    )

    return agent_card
