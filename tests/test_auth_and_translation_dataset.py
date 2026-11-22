from pathlib import Path
from unittest.mock import AsyncMock, MagicMock
import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app
from app.services.auth import AuthService
from app.services.llm import LLMResponse
from app.services.translation_cache import CachedTranslation, TranslationCacheService
from app.services.translation_dataset import backfill_and_annotate_translations


def test_auth_service_local_and_google_sessions() -> None:
    auth = AuthService(db_path=Path(":memory:"))
    user = auth.register_user("alice@example.com", "StrongPass123", display_name="Alice")
    assert user.email == "alice@example.com"
    assert user.auth_provider == "local"

    with pytest.raises(ValueError):
        auth.register_user("alice@example.com", "OtherPass123")

    assert auth.authenticate_user("alice@example.com", "wrong") is None
    authed = auth.authenticate_user("alice@example.com", "StrongPass123")
    assert authed is not None and authed.id == user.id

    tok = auth.create_session(user.id)
    assert auth.get_user_by_session(tok) is not None
    auth.revoke_session(tok)
    assert auth.get_user_by_session(tok) is None

    g_user = auth.upsert_google_user("sub-123", "bob@gmail.com", "Bob")
    assert g_user.auth_provider == "google"
    auth.close()


@pytest.mark.asyncio
async def test_auth_endpoints_register_me_logout_login(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from app.api import deps

    test_auth = AuthService(db_path=tmp_path / "users.db")
    monkeypatch.setattr(deps, "_auth_service", test_auth)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        me0 = await ac.get("/api/v1/auth/me")
        assert me0.status_code == 200
        assert me0.json()["authenticated"] is False

        reg = await ac.post(
            "/api/v1/auth/register",
            json={"email": "user@example.com", "password": "Password123", "display_name": "Tester"},
        )
        assert reg.status_code == 200
        assert reg.json()["user"]["email"] == "user@example.com"

        me1 = await ac.get("/api/v1/auth/me")
        assert me1.json()["authenticated"] is True
        assert me1.json()["user"]["display_name"] == "Tester"

        out = await ac.post("/api/v1/auth/logout")
        assert out.status_code == 200
        me2 = await ac.get("/api/v1/auth/me")
        assert me2.json()["authenticated"] is False

        login = await ac.post(
            "/api/v1/auth/login",
            json={"email": "user@example.com", "password": "Password123"},
        )
        assert login.status_code == 200
        assert login.json()["authenticated"] is True
    test_auth.close()


@pytest.mark.asyncio
async def test_backfill_and_annotate_translations(tmp_path: Path) -> None:
    cache = TranslationCacheService(db_path=tmp_path / "tr.db")
    cache.upsert(
        CachedTranslation(
            normalized_term="cooking potatoes",
            source_lang="en",
            target_lang="cs",
            translated_term="brambory konzumní",
            category="vegetables",
        )
    )

    mock_llm = MagicMock()
    mock_llm.model = "gemini-3.5-flash"
    mock_llm._extract_json = MagicMock(
        return_value={
            "is_accurate": False,
            "accuracy_score": 0.6,
            "recommended_term": "brambory",
            "reason": "Remove overly narrow adjective 'konzumní'",
        }
    )
    mock_llm.generate = AsyncMock(
        return_value=LLMResponse(text='{"is_accurate": false}')
    )

    mock_mon = MagicMock()
    mock_mon.is_active = True
    mock_span = MagicMock()
    mock_span.trace_id = "tr-1"
    mock_span.id = "obs-1"
    mock_mon.trace_generation.return_value.__enter__ = MagicMock(return_value=mock_span)
    mock_mon.trace_generation.return_value.__exit__ = MagicMock(return_value=False)

    ds_file = tmp_path / "translations.jsonl"
    res = await backfill_and_annotate_translations(
        cache_service=cache,
        llm=mock_llm,
        monitoring=mock_mon,
        dataset_path=ds_file,
        langfuse_dataset_name="grocery-translation-accuracy",
    )
    assert res["total_records"] == 1
    assert res["annotated"] == 1
    assert res["adjustments_recommended"] == 1
    mock_mon.log_dataset_item.assert_called_once()
    mock_mon.record_score.assert_called_once()
    assert ds_file.exists()
    cache.close()
