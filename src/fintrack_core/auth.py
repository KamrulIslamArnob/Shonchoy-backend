"""Managed identity verification and atomic private workspace provisioning.

No password/provider token is accepted here. JWT signing keys are fetched only
from the configured Neon origin, never from an untrusted token header.
"""

from datetime import UTC, datetime
from functools import lru_cache
from typing import Annotated, Any
from urllib.parse import urlsplit
from uuid import NAMESPACE_URL, uuid4, uuid5

import jwt
from fastapi import Depends, Header, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials
from sqlalchemy import Column, DateTime, MetaData, String, Table, cast, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from fintrack_core.database import auth_session, session
from fintrack_core.finance.models import AppUser, Workspace
from fintrack_core.routes import bearer

# Read-only projection of the managed table; Alembic must never create/alter it.
managed_sessions = Table(
    "session",
    MetaData(),
    Column("id", String),
    Column("userId", String),
    Column("expiresAt", DateTime(timezone=True)),
    schema="neon_auth",
)


@lru_cache(maxsize=8)
def signing_keys(base_url: str) -> jwt.PyJWKClient:
    return jwt.PyJWKClient(base_url + "/.well-known/jwks.json", timeout=5, lifespan=300)


def verify_token(base_url: str | None, token: str) -> dict[str, Any]:
    parsed = urlsplit(base_url or "")
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username
        or parsed.query
        or parsed.fragment
    ):
        raise HTTPException(503, "Managed authentication is not configured.")
    origin = f"https://{parsed.netloc}"
    try:
        key = signing_keys((base_url or "").rstrip("/")).get_signing_key_from_jwt(token)
        claims: dict[str, Any] = jwt.decode(
            token,
            key.key,
            algorithms=["EdDSA"],
            issuer=origin,
            audience=origin,
            # Managed issuer and API hosts can differ by a few seconds. Keep
            # signature, issuer, audience, and all time checks enabled.
            leeway=30,
            options={"require": ["sub", "exp", "iat", "iss", "aud"]},
        )
        if (
            not isinstance(claims["sub"], str)
            or not 0 < len(claims["sub"]) <= 255
            or claims.get("banned")
        ):
            raise jwt.InvalidTokenError()
        return claims
    except jwt.PyJWKClientConnectionError:
        raise HTTPException(
            503, "Authentication verification is temporarily unavailable."
        ) from None
    except jwt.PyJWTError:
        raise HTTPException(401, "A valid signed-in session is required.") from None


def authenticated_identity(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
    auth_db: Annotated[Session, Depends(auth_session)],
    session_id: Annotated[str | None, Header(alias="X-Neon-Session-Id", max_length=255)] = None,
) -> dict[str, Any]:
    if not credentials or not session_id:
        raise HTTPException(401, "A valid signed-in session is required.")
    settings = request.app.state.settings
    claims = verify_token(settings.neon_auth_url, credentials.credentials)
    with auth_db.begin():
        active = auth_db.scalar(
            select(managed_sessions.c.id).where(
                cast(managed_sessions.c.id, String) == session_id,
                cast(managed_sessions.c.userId, String) == claims["sub"],
                managed_sessions.c.expiresAt > datetime.now(UTC),
            )
        )
        if active is None:
            raise HTTPException(401, "Your session has ended. Sign in again.")
    request.state.auth_subject = claims["sub"]
    return claims


def authenticated_access(
    request: Request,
    db: Annotated[Session, Depends(session)],
    claims: Annotated[dict[str, Any], Depends(authenticated_identity)],
) -> None:
    fingerprint_key = request.app.state.settings.command_fingerprint_key
    if fingerprint_key is None or len(fingerprint_key.get_secret_value()) < 32:
        raise HTTPException(503, "Private workspace commands are not configured.")
    # Stable across devices and simultaneous first-login requests, isolated across auth issuers.
    scope = uuid5(NAMESPACE_URL, f"shonchoy:{claims['iss']}:{claims['sub']}")
    db.info["workspace_scope"] = str(scope)
    with db.begin():
        insert = pg_insert if db.get_bind().dialect.name == "postgresql" else sqlite_insert
        request.state.core_scope_id = str(scope)
        # These inserts commit together. No existing/shared workspace can be claimed by a client.
        name = str(claims.get("name") or "Your workspace")[:120]
        db.execute(insert(Workspace).values(id=scope, name=name).on_conflict_do_nothing())
        db.execute(
            insert(AppUser)
            .values(
                id=uuid4(),
                auth_issuer=claims["iss"],
                auth_subject=claims["sub"],
                workspace_id=scope,
            )
            .on_conflict_do_nothing(index_elements=["auth_issuer", "auth_subject"])
        )
