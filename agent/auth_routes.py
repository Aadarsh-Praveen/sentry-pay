"""
agent/auth_routes.py
─────────────────────────────────────────────────────────────────────────────
All FastAPI endpoints related to auth, Gmail, and feedback.

Mounted by api.py via `app.include_router(auth_router)`.

Endpoints:
  Auth:
    GET  /auth/google              → returns Google OAuth URL
    GET  /auth/callback?code=...   → exchanges code, returns JWT (HTML redirect)
    GET  /auth/me                  → returns current user profile (JWT required)
    POST /auth/logout              → no-op (frontend just discards JWT)

  Gmail:
    POST /gmail/scan               → kick off 90-day baseline build (background)
    GET  /gmail/scan/progress      → poll progress of baseline build
    GET  /gmail/status             → connection status + baseline_built flag
    GET  /gmail/emails             → list scanned email verdicts

  Feedback:
    POST /feedback/confirm-block   → confirm a BLOCK was correct
    POST /feedback/mark-safe       → mark a verdict as false positive
    POST /feedback/confirm-allow   → confirm an ALLOW was correct
    GET  /learning/stats           → aggregate feedback statistics
"""

from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from fastapi.responses import RedirectResponse
from pydantic import BaseModel

from config.elastic_client import get_client
from agent.auth import (
    create_jwt,
    exchange_code_for_tokens,
    fetch_google_profile,
    get_authorization_url,
    get_current_user,
    upsert_user,
    USERS_TABLE,
    _bq,
)
from agent.history_builder  import build_baseline, get_progress
from agent.feedback_handler import (
    confirm_allow,
    confirm_block,
    get_learning_stats,
    mark_safe,
)

log = logging.getLogger("sentry-pay.auth-routes")

router = APIRouter()

# Frontend URL — used to redirect after OAuth callback
FRONTEND_URL = "http://localhost:5173"


# ────────────────────────────────────────────────────────────────────────────
# AUTH
# ────────────────────────────────────────────────────────────────────────────
@router.get("/auth/google")
def start_oauth():
    """Returns the Google OAuth URL the frontend should redirect the user to."""
    auth_url, state = get_authorization_url()
    return {"authorization_url": auth_url, "state": state}


@router.get("/auth/callback")
async def oauth_callback(code: str = Query(...), state: Optional[str] = Query(None)):
    """
    Google redirects here after consent. Exchange code → tokens → JWT.
    Redirects to frontend with JWT in URL fragment.
    """
    # 1. Exchange code for tokens
    tokens  = await exchange_code_for_tokens(code)
    # 2. Fetch user profile from Google
    profile = await fetch_google_profile(tokens["access_token"])
    # 3. Store user + tokens in BigQuery
    user, is_new_user = upsert_user(profile, tokens)
    # 4. Create JWT for frontend
    jwt_token = create_jwt(user)
    log.info(f"[auth] User {user.email} logged in (new_user={is_new_user})")

    # 5. Redirect to frontend with JWT in URL fragment
    #    Frontend reads window.location.hash, stores JWT, then cleans URL
    redirect_url = (
        f"{FRONTEND_URL}/#jwt={jwt_token}"
        f"&new_user={'true' if is_new_user else 'false'}"
        f"&email={user.email}"
    )
    return RedirectResponse(url=redirect_url, status_code=302)


@router.get("/auth/me")
def get_me(user: dict = Depends(get_current_user)):
    """Return the current user's JWT payload (sub=user_id, email, name)."""
    return {
        "user_id": user["sub"],
        "email":   user["email"],
        "name":    user.get("name", ""),
    }


@router.post("/auth/logout")
def logout(user: dict = Depends(get_current_user)):
    """No-op — JWT is stateless. Frontend just discards it."""
    return {"status": "logged_out"}


# ────────────────────────────────────────────────────────────────────────────
# GMAIL
# ────────────────────────────────────────────────────────────────────────────
@router.post("/gmail/scan")
def start_baseline_build(
    background_tasks: BackgroundTasks,
    user:             dict = Depends(get_current_user),
):
    """Kick off the 90-day Gmail history scan as a background task."""
    user_id = user["sub"]
    progress = get_progress(user_id)
    if progress.get("status") in {"scanning", "extracting", "indexing", "computing_baseline"}:
        return {"status": "already_running", "progress": progress}

    background_tasks.add_task(build_baseline, user_id, 90)
    return {"status": "started", "user_id": user_id}


@router.get("/gmail/scan/progress")
def get_baseline_progress(user: dict = Depends(get_current_user)):
    """Poll the progress of the baseline build."""
    return get_progress(user["sub"])


@router.get("/gmail/status")
def get_gmail_status(user: dict = Depends(get_current_user)):
    """Return Gmail connection status + baseline_built flag."""
    user_id = user["sub"]
    query = f"""
        SELECT email, baseline_built, last_login
        FROM `{USERS_TABLE}` WHERE user_id = @user_id LIMIT 1
    """
    from google.cloud import bigquery
    rows = list(_bq.query(query, job_config=bigquery.QueryJobConfig(
        query_parameters=[bigquery.ScalarQueryParameter("user_id", "STRING", user_id)]
    )).result())
    if not rows:
        raise HTTPException(404, "User not found")
    row = rows[0]
    return {
        "email":          row.email,
        "baseline_built": bool(row.baseline_built),
        "last_login":     row.last_login.isoformat() if row.last_login else None,
        "connected":      True,
    }


@router.get("/gmail/emails")
def list_email_verdicts(
    user:    dict = Depends(get_current_user),
    limit:   int  = Query(50, ge=1, le=200),
    verdict: Optional[str] = Query(None),
):
    """List the user's scanned email verdicts."""
    user_id = user["sub"]
    must = [{"term": {"user_id": user_id}}]
    if verdict:
        must.append({"term": {"agent_verdict": verdict.upper()}})

    es = get_client()
    resp = es.search(
        index="email_verdicts",
        body={
            "query": {"bool": {"must": must}},
            "sort":  [{"timestamp": "desc"}],
            "size":  limit,
        },
    )
    return [h["_source"] for h in resp["hits"]["hits"]]


# ────────────────────────────────────────────────────────────────────────────
# FEEDBACK
# ────────────────────────────────────────────────────────────────────────────
class FeedbackRequest(BaseModel):
    verdict_id: str
    note:       Optional[str] = None


@router.post("/feedback/confirm-block")
def feedback_confirm_block(
    req:  FeedbackRequest,
    user: dict = Depends(get_current_user),
):
    return confirm_block(req.verdict_id, user["sub"], req.note)


@router.post("/feedback/mark-safe")
def feedback_mark_safe(
    req:  FeedbackRequest,
    user: dict = Depends(get_current_user),
):
    return mark_safe(req.verdict_id, user["sub"], req.note)


@router.post("/feedback/confirm-allow")
def feedback_confirm_allow(
    req:  FeedbackRequest,
    user: dict = Depends(get_current_user),
):
    return confirm_allow(req.verdict_id, user["sub"])


@router.get("/learning/stats")
def learning_stats(
    user: dict = Depends(get_current_user),
    all_users: bool = Query(False),
):
    """Get learning stats — per user by default, or global if all_users=true."""
    return get_learning_stats(None if all_users else user["sub"])

# ─── Manual monitor trigger (for testing) ─────────────────────────────
@router.post("/gmail/check-now")
async def check_gmail_now(current_user: dict = Depends(get_current_user)):
    """Manually trigger an immediate Gmail check for the current user."""
    from agent.email_monitor import check_user_now
    try:
        result = check_user_now(current_user["user_id"], lookback_minutes=60)
        return result
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Check failed: {exc}")


"""
─────────────────────────────────────────────────────────────────────────────
Adds /auth/demo — a no-OAuth shortcut for hackathon judges to enter the app
as the pre-built sentrypaydemo@gmail.com account.
"""

import os
from datetime import datetime, timedelta, timezone
from fastapi    import HTTPException
from google.cloud import bigquery
from jose       import jwt

DEMO_USER_EMAIL = os.getenv("DEMO_USER_EMAIL", "sentrypaydemo@gmail.com")
_GCP_PROJECT    = os.getenv("GCP_PROJECT_ID")
_BQ_DATASET     = os.getenv("BIGQUERY_DATASET", "sentry_pay")
_USERS_TABLE    = f"{_GCP_PROJECT}.{_BQ_DATASET}.users"
_JWT_SECRET     = os.getenv("JWT_SECRET", "sentry-pay-jwt-secret-2026")


@router.post("/auth/demo")
async def auth_demo():
    """
    Issue a JWT for the demo account — no OAuth required.
    Used by hackathon judges to skip the Google sign-in flow.

    Returns {jwt, user} matching the shape of /auth/callback.
    """
    bq = bigquery.Client(project=_GCP_PROJECT)
    query = f"""
        SELECT user_id, email, name, picture
        FROM `{_USERS_TABLE}`
        WHERE email = @email LIMIT 1
    """
    job_config = bigquery.QueryJobConfig(
        query_parameters=[bigquery.ScalarQueryParameter("email", "STRING", DEMO_USER_EMAIL)]
    )
    rows = list(bq.query(query, job_config=job_config).result())

    if not rows:
        raise HTTPException(
            status_code=404,
            detail=(
                f"Demo account ({DEMO_USER_EMAIL}) not found in BigQuery. "
                f"Sign in with that account once via OAuth first to seed it."
            ),
        )

    user = rows[0]

    # Issue a 7-day JWT
    now = datetime.now(timezone.utc)
    payload = {
        "sub":   user.user_id,
        "email": user.email,
        "name":  user.name or "Demo User",
        "demo":  True,
        "iat":   int(now.timestamp()),
        "exp":   int((now + timedelta(days=7)).timestamp()),
    }
    token = jwt.encode(payload, _JWT_SECRET, algorithm="HS256")

    return {
        "jwt": token,
        "user": {
            "user_id": user.user_id,
            "email":   user.email,
            "name":    user.name or "Demo User",
        },
    }
