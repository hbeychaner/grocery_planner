from pathlib import Path
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastmcp import Client
from fastmcp.client.transports import StreamableHttpTransport
import httpx
import pytest

from app.mcp_server import create_mcp_server
from app.services.auth import AuthService, anonymize_user_id


def test_obo_jwt_mint_verify_and_anonymize(tmp_path: Path) -> None:
    auth = AuthService(db_path=tmp_path / "auth.db")
    user = auth.register_user("secret.email@example.com", "pw123456", "Secret Name")

    anon = anonymize_user_id(user.id)
    assert anon.startswith("usr_")
    assert "secret" not in anon
    assert user.id not in anon

    token = auth.mint_obo_jwt(user.id)
    claims = auth.verify_obo_jwt(token)
    assert claims is not None
    assert claims["sub"] == user.id
    assert claims["anon_id"] == anon
    assert "groceries:read" in claims["scope"]
    assert "email" not in claims
    auth.close()


@pytest.mark.asyncio
async def test_mcp_jwt_verifier_enforces_obo_token(tmp_path: Path) -> None:
    auth = AuthService(db_path=tmp_path / "auth.db")
    user = auth.register_user("obo@example.com", "pw123456", "OBO User")
    seen_auth_headers: list[str] = []

    mini_app = FastAPI()

    @mini_app.get("/api/v1/staples")
    async def list_staples_mock(request: Request) -> JSONResponse:
        seen_auth_headers.append(request.headers.get("authorization", ""))
        return JSONResponse([{"name": "butter"}])

    mcp = create_mcp_server(mini_app, obo_public_key_pem=auth.obo_public_key_pem)
    mcp_http = mcp.http_app(path="/")

    def _make_asgi_client(**kwargs):  # type: ignore[no-untyped-def]
        kwargs.pop("transport", None)
        kwargs.pop("auth", None)
        return httpx.AsyncClient(
            transport=httpx.ASGITransport(app=mcp_http),
            base_url="http://testserver",
            **kwargs,
        )

    async with mcp_http.lifespan(mcp_http):
        # Valid OBO JWT succeeds and forwards Authorization: Bearer <obo_jwt> to FastAPI
        obo_jwt = auth.mint_obo_jwt(user.id)
        transport = StreamableHttpTransport(
            url="http://testserver/",
            headers={"Authorization": f"Bearer {obo_jwt}"},
            httpx_client_factory=_make_asgi_client,
        )
        async with Client(transport) as client:
            tools = await client.list_tools()
            assert len(tools) == 1
            res = await client.call_tool(tools[0].name, {})
            assert res is not None
        assert seen_auth_headers == [f"Bearer {obo_jwt}"]

        # Invalid JWT is rejected by JWTVerifier (401)
        bad_transport = StreamableHttpTransport(
            url="http://testserver/",
            headers={"Authorization": "Bearer not-a-valid-jwt"},
            httpx_client_factory=_make_asgi_client,
        )
        with pytest.raises(Exception):
            async with Client(bad_transport) as bad_client:
                await bad_client.list_tools()

    auth.close()
