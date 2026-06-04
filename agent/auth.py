"""
agent/auth.py
─────────────────────────────────────────────────────────────────────────────
Google OAuth 2.0 login + JWT session management for SentryPay.

Flow:
  1. Frontend calls GET /auth/google → redirects user to Google
  2. User logs in, grants permissions
  3. Google redirects to /auth/callback?code=...
  4. We exchange code for access_token + refresh_token (Gmail scopes)
  5. We fetch user's profile (email, name, photo)
  6. We store user + Gmail tokens in BigQuery (sentry_pay.users)
  7. We create a JWT for the frontend session
  8. Frontend stores JWT in localStorage, sends in Authorization header
"""

from __future__ import annotations

import hashlib
import os
import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional

import httpx
from fastapi import HTTPException, Header, status
from google.cloud import bigquery
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow
from jose import JWTError, jwt
from pydantic import BaseModel


# ── Configuration ────────────────────────────────────────────────────────────
import os
GOOGLE_CLIENT_ID      = os.getenv("GOOGLE_CLIENT_ID")
GOOGLE_CLIENT_SECRET  = os.getenv("GOOGLE_CLIENT_SECRET")
GOOGLE_REDIRECT_URI   = os.getenv("GOOGLE_REDIRECT_URI",   "http://localhost:8000/auth/callback")
JWT_SECRET            = os.getenv("JWT_SECRET",            "sentry-pay-jwt-secret-2026")
GCP_PROJECT           = os.getenv("GCP_PROJECT_ID")
BQ_DATASET            = os.getenv("BIGQUERY_DATASET",      "sentry_pay")

JWT_ALGORITHM         = "HS256"
JWT_EXPIRY_HOURS      = 24
USERS_TABLE           = f"{GCP_PROJECT}.{BQ_DATASET}.users"

# Gmail scopes — readonly + labels + modify (apply labels)
GMAIL_SCOPES = [
    "openid",
    "https://www.googleapis.com/auth/userinfo.email",
    "https://www.googleapis.com/auth/userinfo.profile",
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.labels",
    "https://www.googleapis.com/auth/gmail.modify",
]

# Allow HTTP redirect URI for local development
if GOOGLE_REDIRECT_URI.startswith("http://"):
    os.environ["OAUTHLIB_INSECURE_TRANSPORT"] = "1"

_bq = bigquery.Client(project=GCP_PROJECT)


# ── Pydantic models ──────────────────────────────────────────────────────────
class UserProfile(BaseModel):
    user_id:    str  # SHA-256 hash of email for privacy
    email:      str
    name:       str
    picture:    Optional[str] = None
    created_at: str


class AuthSession(BaseModel):
    jwt_token:    str
    user:         UserProfile
    is_new_user:  bool  # True if first login → frontend should kick off Gmail scan


# ── Helpers ──────────────────────────────────────────────────────────────────
def hash_email(email: str) -> str:
    """SHA-256 hash of email — used as user_id for privacy."""
    return hashlib.sha256(email.lower().strip().encode()).hexdigest()[:16]


def _build_flow(state: Optional[str] = None) -> Flow:
    """Build OAuth flow object (PKCE disabled to keep token exchange stateless)."""
    flow = Flow.from_client_config(
        {
            "web": {
                "client_id":     GOOGLE_CLIENT_ID,
                "client_secret": GOOGLE_CLIENT_SECRET,
                "auth_uri":      "https://accounts.google.com/o/oauth2/auth",
                "token_uri":     "https://oauth2.googleapis.com/token",
                "redirect_uris": [GOOGLE_REDIRECT_URI],
            }
        },
        scopes=GMAIL_SCOPES,
        state=state,
        autogenerate_code_verifier=False,
    )
    flow.redirect_uri = GOOGLE_REDIRECT_URI
    return flow


# ── OAuth flow ───────────────────────────────────────────────────────────────
def get_authorization_url() -> tuple[str, str]:
    """
    Returns (authorization_url, state) — frontend redirects user to this URL.

    state is a CSRF token; we verify it on callback.
    """
    state = secrets.token_urlsafe(32)
    flow  = _build_flow(state=state)
    auth_url, _ = flow.authorization_url(
        access_type="offline",            # so we get a refresh_token
        include_granted_scopes="true",
        prompt="consent",                 # force consent screen → always returns refresh_token
    )
    return auth_url, state


async def exchange_code_for_tokens(code: str) -> dict:
    """
    Exchange the auth code for access_token + refresh_token.
    Done manually via httpx to avoid PKCE state issues.
    """
    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.post(
            "https://oauth2.googleapis.com/token",
            data={
                "code":          code,
                "client_id":     GOOGLE_CLIENT_ID,
                "client_secret": GOOGLE_CLIENT_SECRET,
                "redirect_uri":  GOOGLE_REDIRECT_URI,
                "grant_type":    "authorization_code",
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )

    if resp.status_code != 200:
        raise HTTPException(
            status_code=400,
            detail=f"Token exchange failed: {resp.text}"
        )

    data = resp.json()
    expires_in   = data.get("expires_in", 3600)
    token_expiry = (datetime.now(timezone.utc) + timedelta(seconds=expires_in)).isoformat()

    return {
        "access_token":  data["access_token"],
        "refresh_token": data.get("refresh_token"),
        "token_expiry":  token_expiry,
        "scopes":        data.get("scope", "").split(),
    }


async def fetch_google_profile(access_token: str) -> dict:
    """Fetch the user's Google profile (email, name, picture)."""
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.get(
            "https://www.googleapis.com/oauth2/v2/userinfo",
            headers={"Authorization": f"Bearer {access_token}"},
        )
    if resp.status_code != 200:
        raise HTTPException(status_code=400, detail="Failed to fetch Google profile")
    return resp.json()


# ── User storage (BigQuery) ──────────────────────────────────────────────────
def ensure_users_table():
    """Create the users table if it doesn't exist."""
    schema = [
        bigquery.SchemaField("user_id",       "STRING", mode="REQUIRED"),
        bigquery.SchemaField("email",         "STRING", mode="REQUIRED"),
        bigquery.SchemaField("name",          "STRING"),
        bigquery.SchemaField("picture",       "STRING"),
        bigquery.SchemaField("gmail_access_token",  "STRING"),
        bigquery.SchemaField("gmail_refresh_token", "STRING"),
        bigquery.SchemaField("gmail_token_expiry",  "STRING"),
        bigquery.SchemaField("created_at",    "TIMESTAMP"),
        bigquery.SchemaField("last_login",    "TIMESTAMP"),
        bigquery.SchemaField("baseline_built","BOOLEAN"),
    ]
    table = bigquery.Table(USERS_TABLE, schema=schema)
    try:
        _bq.create_table(table)
        print(f"[auth] Created users table: {USERS_TABLE}")
    except Exception:
        pass  # Already exists


def upsert_user(profile: dict, tokens: dict) -> tuple[UserProfile, bool]:
    """
    Insert new user or update existing one's tokens.

    Returns (UserProfile, is_new_user).
    """
    user_id    = hash_email(profile["email"])
    now        = datetime.now(timezone.utc)
    now_iso    = now.isoformat()

    # Check if user exists
    query = f"""
        SELECT user_id, baseline_built FROM `{USERS_TABLE}`
        WHERE user_id = @user_id LIMIT 1
    """
    job_config = bigquery.QueryJobConfig(
        query_parameters=[bigquery.ScalarQueryParameter("user_id", "STRING", user_id)]
    )
    rows = list(_bq.query(query, job_config=job_config).result())
    is_new_user = len(rows) == 0

    if is_new_user:
        # Insert new user
        _bq.insert_rows_json(USERS_TABLE, [{
            "user_id":               user_id,
            "email":                 profile["email"],
            "name":                  profile.get("name", ""),
            "picture":               profile.get("picture"),
            "gmail_access_token":    tokens["access_token"],
            "gmail_refresh_token":   tokens.get("refresh_token"),
            "gmail_token_expiry":    tokens.get("token_expiry"),
            "created_at":            now_iso,
            "last_login":            now_iso,
            "baseline_built":        False,
        }])
    else:
        # Update tokens + last_login for existing user
        # (using MERGE since BigQuery doesn't allow UPDATE on streaming buffer)
        update_query = f"""
            UPDATE `{USERS_TABLE}`
            SET gmail_access_token  = @access_token,
                gmail_refresh_token = COALESCE(@refresh_token, gmail_refresh_token),
                gmail_token_expiry  = @token_expiry,
                last_login          = TIMESTAMP(@last_login)
            WHERE user_id = @user_id
        """
        try:
            _bq.query(update_query, job_config=bigquery.QueryJobConfig(
                query_parameters=[
                    bigquery.ScalarQueryParameter("access_token",  "STRING", tokens["access_token"]),
                    bigquery.ScalarQueryParameter("refresh_token", "STRING", tokens.get("refresh_token")),
                    bigquery.ScalarQueryParameter("token_expiry",  "STRING", tokens.get("token_expiry")),
                    bigquery.ScalarQueryParameter("last_login",    "STRING", now_iso),
                    bigquery.ScalarQueryParameter("user_id",       "STRING", user_id),
                ]
            )).result()
        except Exception as exc:
            print(f"[auth] Token update failed (streaming buffer?): {exc}")

    user_profile = UserProfile(
        user_id    = user_id,
        email      = profile["email"],
        name       = profile.get("name", ""),
        picture    = profile.get("picture"),
        created_at = now_iso,
    )
    return user_profile, is_new_user


def get_user_tokens(user_id: str) -> Optional[dict]:
    """Fetch a user's stored Gmail tokens from BigQuery."""
    query = f"""
        SELECT gmail_access_token, gmail_refresh_token, gmail_token_expiry
        FROM `{USERS_TABLE}` WHERE user_id = @user_id LIMIT 1
    """
    job_config = bigquery.QueryJobConfig(
        query_parameters=[bigquery.ScalarQueryParameter("user_id", "STRING", user_id)]
    )
    rows = list(_bq.query(query, job_config=job_config).result())
    if not rows:
        return None
    row = rows[0]
    return {
        "access_token":  row.gmail_access_token,
        "refresh_token": row.gmail_refresh_token,
        "token_expiry":  row.gmail_token_expiry,
    }


def mark_baseline_built(user_id: str):
    """Flag that the user's 90-day baseline has been built."""
    query = f"""
        UPDATE `{USERS_TABLE}` SET baseline_built = TRUE
        WHERE user_id = @user_id
    """
    try:
        _bq.query(query, job_config=bigquery.QueryJobConfig(
            query_parameters=[bigquery.ScalarQueryParameter("user_id", "STRING", user_id)]
        )).result()
    except Exception as exc:
        print(f"[auth] mark_baseline_built failed: {exc}")


# ── JWT session tokens ───────────────────────────────────────────────────────
def create_jwt(user: UserProfile) -> str:
    """Create a JWT for the frontend session."""
    payload = {
        "sub":   user.user_id,
        "email": user.email,
        "name":  user.name,
        "exp":   datetime.now(timezone.utc) + timedelta(hours=JWT_EXPIRY_HOURS),
        "iat":   datetime.now(timezone.utc),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


def decode_jwt(token: str) -> dict:
    """Decode and validate a JWT. Raises HTTPException(401) on failure."""
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        return payload
    except JWTError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Invalid or expired token: {exc}",
        )


# ── FastAPI dependency: extract current user from JWT ────────────────────────
def get_current_user(authorization: Optional[str] = Header(default=None)) -> dict:
    """
    FastAPI dependency. Extracts JWT from Authorization header.
    Use as: @app.get(...) def endpoint(user: dict = Depends(get_current_user))
    """
    if not authorization:
        raise HTTPException(status_code=401, detail="Missing Authorization header")
    if not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="Authorization must be 'Bearer <jwt>'")
    token = authorization.split(" ", 1)[1].strip()
    return decode_jwt(token)


# ── Initialize on import ─────────────────────────────────────────────────────
ensure_users_table()