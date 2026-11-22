from pathlib import Path
import pytest

from app.core.config import settings
from app.services.auth import AuthService, DailySignupLimitError


def test_daily_new_user_signup_limit(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "max_new_users_per_day", 5)
    auth = AuthService(db_path=tmp_path / "auth.db")

    for i in range(5):
        u = auth.register_user(f"user{i}@example.com", "secret123", f"User {i}")
        assert u.email == f"user{i}@example.com"

    # 6th new local registration today is blocked
    with pytest.raises(DailySignupLimitError):
        auth.register_user("user5@example.com", "secret123", "User 5")

    # 6th new Google OAuth user today is also blocked
    with pytest.raises(DailySignupLimitError):
        auth.upsert_google_user("sub-new", "newgoogle@example.com", "New Google")

    # Existing user can still sign in via local auth or Google upsert
    existing = auth.authenticate_user("user0@example.com", "secret123")
    assert existing is not None
    existing_google = auth.upsert_google_user("sub-0", "user0@example.com", "User 0")
    assert existing_google.id == existing.id
    auth.close()


def test_daily_chat_quota_per_user(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "max_chats_per_user_per_day", 3)
    auth = AuthService(db_path=tmp_path / "auth.db")

    u1 = auth.register_user("alice@example.com", "secret123", "Alice")
    u2 = auth.register_user("bob@example.com", "secret123", "Bob")

    assert auth.consume_daily_chat_quota(u1.id) == (True, 2)
    assert auth.consume_daily_chat_quota(u1.id) == (True, 1)
    assert auth.consume_daily_chat_quota(u1.id) == (True, 0)
    # 4th chat for Alice today is blocked
    assert auth.consume_daily_chat_quota(u1.id) == (False, 0)

    # Bob still has his own 3-chat daily quota
    assert auth.consume_daily_chat_quota(u2.id) == (True, 2)
    auth.close()
