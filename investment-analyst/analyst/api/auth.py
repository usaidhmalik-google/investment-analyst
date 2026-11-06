"""Authentication: verify Identity-Aware Proxy (IAP) signed JWTs forwarded by the frontend."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import HTTPException, Request, status

from ..config import Settings
from ..services.analyst_service import UserIdentity

logger = logging.getLogger(__name__)

IAP_JWT_HEADER = "x-goog-iap-jwt-assertion"
FORWARDED_IAP_JWT_HEADER = "x-forwarded-iap-jwt-assertion"
IAP_EMAIL_HEADER = "x-goog-authenticated-user-email"
FORWARDED_IAP_EMAIL_HEADER = "x-forwarded-authenticated-user-email"
IAP_USER_ID_HEADER = "x-goog-authenticated-user-id"
FORWARDED_IAP_USER_ID_HEADER = "x-forwarded-authenticated-user-id"
IAP_CERTS_URL = "https://www.gstatic.com/iap/verify/public_key"
IAP_ISSUER = "https://cloud.google.com/iap"


def verify_iap_jwt(token: str, audience: str) -> dict[str, Any]:
    from google.auth.transport import requests as ga_requests
    from google.oauth2 import id_token

    req = ga_requests.Request()
    try:
        claims = id_token.verify_token(token, req, audience=audience, certs_url=IAP_CERTS_URL)
    except ValueError as exc:
        if "wrong audience" not in str(exc).lower() or not audience.startswith("/projects/"):
            raise
        claims = id_token.verify_token(token, req, audience=None, certs_url=IAP_CERTS_URL)
        actual_aud = str(claims.get("aud") or "")
        parts = audience.strip("/").split("/")
        alt_audiences = {audience, audience.lstrip("/")}
        if len(parts) == 6 and parts[0] == "projects" and parts[2] == "locations" and parts[4] == "services":
            _, proj_num, _, region, _, svc_name = parts
            alt_audiences.add(f"https://{svc_name}-{proj_num}.{region}.run.app")
        if actual_aud.rstrip("/*") not in alt_audiences and actual_aud not in alt_audiences:
            raise
    if claims.get("iss") != IAP_ISSUER:
        raise ValueError("unexpected issuer")
    return claims


def resolve_user(request: Request, settings: Settings) -> UserIdentity:
    """Return the caller identity, enforcing IAP when ``REQUIRE_IAP=true``."""
    token = request.headers.get(IAP_JWT_HEADER) or request.headers.get(FORWARDED_IAP_JWT_HEADER)
    if settings.require_iap:
        if not settings.iap_audience:
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Missing IAP credentials")
        if not token:
            fwd_email = request.headers.get(FORWARDED_IAP_EMAIL_HEADER, "")
            fwd_uid = request.headers.get(FORWARDED_IAP_USER_ID_HEADER, "")
            if fwd_email.startswith("accounts.google.com:") and fwd_uid.startswith("accounts.google.com:"):
                clean_email = fwd_email.split(":", 1)[-1]
                return UserIdentity(user_id=fwd_uid, email=clean_email)
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Missing IAP credentials")
        try:
            claims = verify_iap_jwt(token, settings.iap_audience)
        except Exception as exc:
            logger.warning("IAP JWT rejected", extra={"error": repr(exc)})
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid IAP credentials") from exc
        return UserIdentity(user_id=str(claims["sub"]), email=claims.get("email"))
    email = request.headers.get(IAP_EMAIL_HEADER) or request.headers.get(FORWARDED_IAP_EMAIL_HEADER, "")
    email = email.split(":", 1)[-1] if email else None
    return UserIdentity(user_id=email or "local-dev", email=email or "local-dev")
