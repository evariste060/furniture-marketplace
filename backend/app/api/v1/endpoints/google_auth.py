"""Continue with Google (ADR-006 amendment 2026-11-11). The storefront's route handlers call
these endpoints: they keep the flow token in a short-lived httpOnly cookie between `start` and
the callback, and the session token in the usual session cookie afterwards."""

from typing import Annotated, Any

from fastapi import APIRouter, BackgroundTasks, Depends, status
from sqlalchemy.orm import Session

from app.api.v1.notifier import Notifier
from app.api.v1.responses import AUTHENTICATED, ERR
from app.core.dependencies import get_current_session, get_current_user
from app.core.rate_limit import LoginRateLimiter, get_google_auth_rate_limiter
from app.core.request_context import RequestContext, get_request_context
from app.db.session import get_db
from app.integrations.oauth import get_google_oauth_client
from app.integrations.oauth.google import GoogleOAuthClient
from app.models.identity import User
from app.models.session import UserSession
from app.schemas.auth import (
    GoogleAuthResponse,
    GoogleCallbackRequest,
    GoogleLinkResponse,
    GoogleStartResponse,
    UserResponse,
)
from app.services.google_auth_service import GoogleAuthService

router = APIRouter(prefix="/auth/google", tags=["Authentication"])

Google = Annotated[GoogleOAuthClient | None, Depends(get_google_oauth_client)]
Limiter = Annotated[LoginRateLimiter, Depends(get_google_auth_rate_limiter)]
Context = Annotated[RequestContext, Depends(get_request_context)]
Db = Annotated[Session, Depends(get_db)]

LIMITS: dict[int | str, dict[str, Any]] = {
    429: {
        **ERR,
        "description": "Too many starts or failed callbacks from this network; see Retry-After",
        "headers": {"Retry-After": {"schema": {"type": "integer"}}},
    },
    503: {
        **ERR,
        "description": (
            "google_auth_unavailable (GOOGLE_OAUTH_* not configured), google_unavailable "
            "(Google unreachable or failing), or login_unavailable (rate-limit store down)"
        ),
    },
}
CALLBACK_ERRORS: dict[int | str, dict[str, Any]] = {
    401: {
        **ERR,
        "description": "google_code_invalid (Google refused the code) or google_token_invalid",
    },
    403: {
        **ERR,
        "description": (
            "google_email_unverified, google_email_invalid, google_staff_not_allowed, or "
            "account_inactive"
        ),
    },
    422: {
        **ERR,
        "description": (
            "Invalid request, google_state_invalid (unknown, expired, already used, or another "
            "browser's flow), google_auth_cancelled (the user cancelled at Google), or "
            "google_auth_failed (another error from Google)"
        ),
    },
    **LIMITS,
}


@router.post(
    "/start",
    response_model=GoogleStartResponse,
    status_code=status.HTTP_200_OK,
    summary="Start Continue with Google",
    description=(
        "Creates a single-use sign-in flow (OAuth 2.0 Authorization Code with PKCE, OpenID "
        "Connect) and returns Google's authorization URL and a `flow_token` that binds the flow "
        "to this browser. The flow expires after GOOGLE_OAUTH_FLOW_TTL_SECONDS (10 minutes by "
        "default).\n\n**Rate limit:** 30 starts and failed callbacks per client network in 15 "
        "minutes (429 with Retry-After)."
    ),
    responses=LIMITS,
)
def start(google: Google, limiter: Limiter, ctx: Context, db: Db) -> GoogleStartResponse:
    url, flow_token, expires_at = GoogleAuthService.start(db, google, limiter, ctx)
    return GoogleStartResponse(authorization_url=url, flow_token=flow_token, expires_at=expires_at)


@router.post(
    "/callback",
    response_model=GoogleAuthResponse,
    status_code=status.HTTP_200_OK,
    summary="Finish Continue with Google",
    description=(
        "Takes Google's answer at the redirect URI (`state` with `code`, or with `error`) and the "
        "browser's `flow_token`. The flow is used once, whatever the outcome. The code is "
        "exchanged with the PKCE verifier and the ID token verified (signature, issuer, "
        "audience, expiry, nonce); the Google email must be verified.\n\n"
        "- Google account already linked: signs in to that customer account.\n"
        "- New Google account whose email no account uses: creates a **customer** account "
        "(`account_created: true`; never staff) and signs in.\n"
        "- Email already used by an account: 409 `google_account_exists`; sign in with the "
        "password, then link Google with /auth/google/link/start.\n\n"
        "Returns the same session as password login (7 days)."
    ),
    responses={
        409: {**ERR, "description": "google_account_exists"},
        **CALLBACK_ERRORS,
    },
)
def callback(
    req: GoogleCallbackRequest,
    google: Google,
    limiter: Limiter,
    ctx: Context,
    db: Db,
    background: BackgroundTasks,
    notifier: Notifier,
) -> GoogleAuthResponse:
    user, token, expires_at, created = GoogleAuthService.callback(db, google, limiter, ctx, req)
    if created:
        notifier.schedule(background, db)  # the welcome email
    return GoogleAuthResponse(
        user=UserResponse.from_user(user),
        session_token=token,
        token_type="bearer",
        expires_at=expires_at,
        account_created=created,
    )


@router.post(
    "/link/start",
    response_model=GoogleStartResponse,
    status_code=status.HTTP_200_OK,
    summary="Start connecting Google to the signed-in account",
    description=(
        "For a signed-in **customer**: like /start, but the flow belongs to this account and can "
        "only link, never sign in. 409 `google_already_linked` when the account already has a "
        "Google account; staff get 403 `google_staff_not_allowed`."
    ),
    responses={
        **AUTHENTICATED,
        403: {**ERR, "description": "google_staff_not_allowed, or account_inactive"},
        409: {**ERR, "description": "google_already_linked"},
        **LIMITS,
    },
)
def link_start(
    google: Google,
    limiter: Limiter,
    ctx: Context,
    db: Db,
    user: Annotated[User, Depends(get_current_user)],
) -> GoogleStartResponse:
    url, flow_token, expires_at = GoogleAuthService.link_start(db, google, limiter, ctx, user)
    return GoogleStartResponse(authorization_url=url, flow_token=flow_token, expires_at=expires_at)


@router.post(
    "/link/callback",
    response_model=GoogleLinkResponse,
    status_code=status.HTTP_200_OK,
    summary="Finish connecting Google to the signed-in account",
    description=(
        "Same checks as /callback, for a flow started with /link/start by the same signed-in "
        "account. Links the Google account (any verified Google email; the account's own email "
        "does not change). 409 `google_account_in_use` when that Google account is linked to "
        "another account, `google_already_linked` when this account already has one."
    ),
    responses={
        **AUTHENTICATED,
        409: {**ERR, "description": "google_account_in_use or google_already_linked"},
        **CALLBACK_ERRORS,
    },
)
def link_callback(
    req: GoogleCallbackRequest,
    google: Google,
    limiter: Limiter,
    ctx: Context,
    db: Db,
    session: Annotated[UserSession, Depends(get_current_session)],
    _: Annotated[User, Depends(get_current_user)],  # active accounts only (403 otherwise)
) -> GoogleLinkResponse:
    linked = GoogleAuthService.link_callback(db, google, limiter, ctx, req, session)
    return GoogleLinkResponse(email=linked.email, linked_at=linked.created_at)
