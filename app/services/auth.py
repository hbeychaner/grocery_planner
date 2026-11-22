"""SQLAlchemy 2.0 user, session, and authentication service (local PBKDF2 + Google OAuth)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import hmac
from pathlib import Path
import secrets
from typing import Optional
import uuid

from pydantic import BaseModel
from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, create_engine, delete, func, select, text
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column
from sqlalchemy.pool import StaticPool

from app.core.config import settings


class AuthBase(DeclarativeBase):
    """Declarative base for user and session tables."""


class UserRecord(AuthBase):
    """Registered user account (local password and/or Google OAuth)."""

    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    email: Mapped[str] = mapped_column(String, unique=True, nullable=False, index=True)
    display_name: Mapped[str] = mapped_column(String, nullable=False)
    password_hash: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    google_sub: Mapped[Optional[str]] = mapped_column(String, unique=True, nullable=True, index=True)
    role: Mapped[str] = mapped_column(String, nullable=False, default="user")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=lambda: datetime.now(timezone.utc)
    )


class SessionRecord(AuthBase):
    """Server-side opaque session token (stored as SHA-256 hash)."""

    __tablename__ = "sessions"

    token_hash: Mapped[str] = mapped_column(String, primary_key=True)
    user_id: Mapped[str] = mapped_column(String, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=lambda: datetime.now(timezone.utc)
    )


class ChatUsageRecord(AuthBase):
    """Per-user chat request log for enforcing daily chat quotas."""

    __tablename__ = "chat_usage"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    used_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=lambda: datetime.now(timezone.utc), index=True
    )


class DailySignupLimitError(ValueError):
    """Raised when the daily cap on new user registrations has been reached."""


class AuthUser(BaseModel):
    """Public user profile returned to API callers."""

    id: str
    email: str
    display_name: str
    role: str = "user"
    auth_provider: str = "local"


def _hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 260_000)
    return f"pbkdf2_sha256$260000${salt.hex()}${dk.hex()}"


def _verify_password(password: str, stored_hash: str) -> bool:
    try:
        scheme, iter_str, salt_hex, dk_hex = stored_hash.split("$", 3)
        if scheme != "pbkdf2_sha256":
            return False
        iterations = int(iter_str)
        dk = hashlib.pbkdf2_hmac(
            "sha256", password.encode("utf-8"), bytes.fromhex(salt_hex), iterations
        )
        return hmac.compare_digest(dk.hex(), dk_hex)
    except Exception:
        return False


def _hash_token(raw_token: str) -> str:
    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()


class AuthService:
    """Manages user accounts, PBKDF2 password verification, Google OAuth upserts, and DB sessions."""

    def __init__(self, db_path: Optional[Path] = None, session_ttl_hours: Optional[int] = None) -> None:
        self.db_path = db_path or settings.users_db_path
        self.session_ttl_hours = session_ttl_hours or settings.session_ttl_hours
        if str(self.db_path) == ":memory:":
            self.engine = create_engine(
                "sqlite:///:memory:",
                connect_args={"check_same_thread": False},
                poolclass=StaticPool,
            )
        else:
            Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
            self.engine = create_engine(
                f"sqlite:///{Path(self.db_path).resolve()}",
                connect_args={"check_same_thread": False, "timeout": 30.0},
            )
            with self.engine.begin() as conn:
                conn.execute(text("PRAGMA journal_mode=WAL"))
                conn.execute(text("PRAGMA busy_timeout=30000"))
        AuthBase.metadata.create_all(self.engine)

    @staticmethod
    def _to_public(rec: UserRecord) -> AuthUser:
        return AuthUser(
            id=rec.id,
            email=rec.email,
            display_name=rec.display_name,
            role=rec.role,
            auth_provider="google" if rec.google_sub else "local",
        )

    @staticmethod
    def _utc_day_start_naive() -> datetime:
        return datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0, tzinfo=None)

    def _check_daily_signup_limit(self, session: Session) -> None:
        limit = settings.max_new_users_per_day
        if limit <= 0:
            return
        day_start = self._utc_day_start_naive()
        count = session.scalar(
            select(func.count()).select_from(UserRecord).where(UserRecord.created_at >= day_start)
        ) or 0
        if count >= limit:
            raise DailySignupLimitError(
                f"Daily new user registration limit reached ({limit} new users/day). Please try again tomorrow."
            )

    def register_user(self, email: str, password: str, display_name: Optional[str] = None) -> AuthUser:
        """Create a new local user account."""
        norm_email = email.strip().lower()
        name = (display_name or norm_email.split("@")[0]).strip()
        with Session(self.engine) as session:
            existing = session.scalar(select(UserRecord).where(UserRecord.email == norm_email))
            if existing is not None:
                raise ValueError("An account with this email already exists")
            self._check_daily_signup_limit(session)
            rec = UserRecord(
                id=str(uuid.uuid4()),
                email=norm_email,
                display_name=name,
                password_hash=_hash_password(password),
                role="user",
                is_active=True,
            )
            session.add(rec)
            session.commit()
            session.refresh(rec)
            return self._to_public(rec)

    def authenticate_user(self, email: str, password: str) -> Optional[AuthUser]:
        """Verify email and password; returns AuthUser or None."""
        norm_email = email.strip().lower()
        with Session(self.engine) as session:
            rec = session.scalar(select(UserRecord).where(UserRecord.email == norm_email))
            if rec is None or not rec.is_active or not rec.password_hash:
                return None
            if not _verify_password(password, rec.password_hash):
                return None
            return self._to_public(rec)

    def upsert_google_user(self, google_sub: str, email: str, display_name: Optional[str] = None) -> AuthUser:
        """Find or create a user authenticated via Google OAuth 2.0."""
        norm_email = email.strip().lower()
        name = (display_name or norm_email.split("@")[0]).strip()
        with Session(self.engine) as session:
            rec = session.scalar(
                select(UserRecord).where(
                    (UserRecord.google_sub == google_sub) | (UserRecord.email == norm_email)
                )
            )
            if rec is None:
                self._check_daily_signup_limit(session)
                rec = UserRecord(
                    id=str(uuid.uuid4()),
                    email=norm_email,
                    display_name=name,
                    google_sub=google_sub,
                    role="user",
                    is_active=True,
                )
                session.add(rec)
            else:
                if not rec.google_sub:
                    rec.google_sub = google_sub
                if display_name and not rec.display_name:
                    rec.display_name = name
            session.commit()
            session.refresh(rec)
            return self._to_public(rec)

    def create_session(self, user_id: str) -> str:
        """Issue an opaque session token and persist its SHA-256 hash."""
        raw_token = secrets.token_urlsafe(32)
        expires_at = datetime.now(timezone.utc) + timedelta(hours=self.session_ttl_hours)
        with Session(self.engine) as session:
            session.add(
                SessionRecord(
                    token_hash=_hash_token(raw_token),
                    user_id=user_id,
                    expires_at=expires_at,
                )
            )
            session.commit()
        return raw_token

    def consume_daily_chat_quota(
        self,
        user_id: str,
        max_per_day: Optional[int] = None,
    ) -> tuple[bool, int]:
        """Consume 1 daily chat slot for user_id. Returns (allowed, remaining)."""
        limit = max_per_day if max_per_day is not None else settings.max_chats_per_user_per_day
        if limit <= 0:
            return True, 0
        day_start = self._utc_day_start_naive()
        with Session(self.engine) as session:
            used_today = session.scalar(
                select(func.count())
                .select_from(ChatUsageRecord)
                .where(
                    ChatUsageRecord.user_id == user_id,
                    ChatUsageRecord.used_at >= day_start,
                )
            ) or 0
            if used_today >= limit:
                return False, 0
            session.add(ChatUsageRecord(user_id=user_id))
            session.commit()
            return True, max(0, limit - used_today - 1)

    def get_user_by_session(self, raw_token: Optional[str]) -> Optional[AuthUser]:
        """Resolve an active, unexpired session token to its AuthUser."""
        if not raw_token:
            return None
        tok_hash = _hash_token(raw_token)
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        with Session(self.engine) as session:
            sess_rec = session.scalar(select(SessionRecord).where(SessionRecord.token_hash == tok_hash))
            if sess_rec is None:
                return None
            exp = sess_rec.expires_at.replace(tzinfo=None) if sess_rec.expires_at.tzinfo else sess_rec.expires_at
            if exp < now:
                session.delete(sess_rec)
                session.commit()
                return None
            user_rec = session.scalar(select(UserRecord).where(UserRecord.id == sess_rec.user_id))
            if user_rec is None or not user_rec.is_active:
                return None
            return self._to_public(user_rec)

    def revoke_session(self, raw_token: Optional[str]) -> None:
        """Delete a session token from the database."""
        if not raw_token:
            return
        tok_hash = _hash_token(raw_token)
        with Session(self.engine) as session:
            session.execute(delete(SessionRecord).where(SessionRecord.token_hash == tok_hash))
            session.commit()

    def close(self) -> None:
        self.engine.dispose()
