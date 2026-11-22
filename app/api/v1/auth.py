"""Authentication, session management, and free Google OAuth 2.0 routes."""

from __future__ import annotations

import secrets
from typing import Optional
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import RedirectResponse
import httpx
from pydantic import BaseModel, Field

from app.api.deps import get_auth_service
from app.core.config import settings
from app.services.auth import AuthService, AuthUser

SESSION_COOKIE_NAME = "gp_session"
OAUTH_STATE_COOKIE_NAME = "gp_oauth_state"

router = APIRouter()
google_oauth_router = APIRouter(tags=["Authentication"])


class RegisterRequest(BaseModel):
    """Payload for creating a local user account."""

    email: str = Field(..., min_length=3, max_length=254)
    password: str = Field(..., min_length=8, max_length=128)
    display_name: Optional[str] = Field(default=None, max_length=80)


class LoginRequest(BaseModel):
    """Payload for email/password login."""

    email: str = Field(..., min_length=3, max_length=254)
    password: str = Field(..., min_length=1, max_length=128)


class AuthStatusResponse(BaseModel):
    """Current authentication and OAuth capability status."""

    authenticated: bool
    user: Optional[AuthUser] = None
    google_oauth_enabled: bool = False


def _is_google_oauth_enabled() -> bool:
    return bool(settings.google_client_id and settings.google_client_secret)


def _set_session_cookie(response: Response, raw_token: str) -> None:
    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=raw_token,
        httponly=True,
        samesite="lax",
        secure=(settings.environment == "production"),
        max_age=settings.session_ttl_hours * 3600,
        path="/",
    )


@router.get("/me", response_model=AuthStatusResponse)
async def get_current_user(
    request: Request,
    auth: AuthService = Depends(get_auth_service),
) -> AuthStatusResponse:
    """Return current session user and whether Google OAuth is configured."""
    token = request.cookies.get(SESSION_COOKIE_NAME)
    user = auth.get_user_by_session(token)
    return AuthStatusResponse(
        authenticated=user is not None,
        user=user,
        google_oauth_enabled=_is_google_oauth_enabled(),
    )


@router.post("/register", response_model=AuthStatusResponse)
async def register(
    payload: RegisterRequest,
    response: Response,
    auth: AuthService = Depends(get_auth_service),
) -> AuthStatusResponse:
    """Register a new local user and open an HttpOnly session."""
    try:
        user = auth.register_user(
            email=payload.email,
            password=payload.password,
            display_name=payload.display_name,
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    token = auth.create_session(user.id)
    _set_session_cookie(response, token)
    return AuthStatusResponse(
        authenticated=True,
        user=user,
        google_oauth_enabled=_is_google_oauth_enabled(),
    )


@router.post("/login", response_model=AuthStatusResponse)
async def login(
    payload: LoginRequest,
    response: Response,
    auth: AuthService = Depends(get_auth_service),
) -> AuthStatusResponse:
    """Authenticate an existing local user and open an HttpOnly session."""
    user = auth.authenticate_user(email=payload.email, password=payload.password)
    if user is None:
        raise HTTPException(status_code=401, detail="Invalid email or password")

    token = auth.create_session(user.id)
    _set_session_cookie(response, token)
    return AuthStatusResponse(
        authenticated=True,
        user=user,
        google_oauth_enabled=_is_google_oauth_enabled(),
    )


@router.post("/logout")
async def logout(
    request: Request,
    response: Response,
    auth: AuthService = Depends(get_auth_service),
) -> dict[str, bool]:
    """Revoke the current session and clear the session cookie."""
    token = request.cookies.get(SESSION_COOKIE_NAME)
    auth.revoke_session(token)
    response.delete_cookie(SESSION_COOKIE_NAME, path="/")
    return {"logged_out": True}


@google_oauth_router.get("/auth/google/login")
async def google_login(request: Request) -> RedirectResponse:
    """Initiate free Google OAuth 2.0 Authorization Code flow."""
    if not _is_google_oauth_enabled():
        raise HTTPException(
            status_code=501,
            detail="Google OAuth is not configured. Set GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET in .env.",
        )

    state = secrets.token_urlsafe(24)
    redirect_uri = settings.google_redirect_uri or str(request.url_for("google_callback"))
    params = urlencode(
        {
            "client_id": settings.google_client_id,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "scope": "openid email profile",
            "state": state,
            "access_type": "online",
            "prompt": "select_account",
        }
    )
    resp = RedirectResponse(url=f"https://accounts.google.com/o/oauth2/v2/auth?{params}", status_code=302)
    resp.set_cookie(
        key=OAUTH_STATE_COOKIE_NAME,
        value=state,
        httponly=True,
        samesite="lax",
        max_age=300,
        path="/",
    )
    return resp


@google_oauth_router.get("/auth/google/callback", name="google_callback")
async def google_callback(
    request: Request,
    code: Optional[str] = None,
    state: Optional[str] = None,
    auth: AuthService = Depends(get_auth_service),
) -> RedirectResponse:
    """Handle Google OAuth 2.0 callback, verify CSRF state, and open a session."""
    if not _is_google_oauth_enabled():
        raise HTTPException(status_code=501, detail="Google OAuth is not configured")

    expected_state = request.cookies.get(OAUTH_STATE_COOKIE_NAME)
    if not code or not state or not expected_state or not secrets.compare_digest(state, expected_state):
        raise HTTPException(status_code=400, detail="Invalid OAuth state or missing authorization code")

    redirect_uri = settings.google_redirect_uri or str(request.url_for("google_callback"))
    async with httpx.AsyncClient(timeout=15.0) as client:
        tok_resp = await client.post(
            "https://oauth2.googleapis.com/token",
            data={
                "code": code,
                "client_id": settings.google_client_id,
                "client_secret": settings.google_client_secret,
                "redirect_uri": redirect_uri,
                "grant_type": "authorization_code",
            },
        )
        if tok_resp.status_code != 200:
            raise HTTPException(status_code=401, detail="Failed to exchange Google OAuth code")

        access_token = tok_resp.json().get("access_token")
        info_resp = await client.get(
            "https://openidconnect.googleapis.com/v1/userinfo",
            headers={"Authorization": f"Bearer {access_token}"},
        )
        if info_resp.status_code != 200:
            raise HTTPException(status_code=401, detail="Failed to fetch Google user profile")

        info = info_resp.json()
        google_sub = str(info.get("sub") or "")
        email = str(info.get("email") or "")
        name = info.get("name")
        if not google_sub or not email:
            raise HTTPException(status_code=400, detail="Google profile missing sub or email")

    user = auth.upsert_google_user(google_sub=google_sub, email=email, display_name=name)
    session_token = auth.create_session(user.id)
    resp = RedirectResponse(url="/", status_code=302)
    resp.delete_cookie(OAUTH_STATE_COOKIE_NAME, path="/")
    _set_session_cookie(resp, session_token)
    return resp
