"""Authentication: verify Identity-Aware Proxy (IAP) signed JWTs forwarded by the frontend."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import HTTPException, Request, status

from ..config import Settings
from ..services.analyst_service import UserIdentity

logger = logging.getLogger(__name__)

IAP_JWT_HEADER = "x-goog-iap-jwt-assertion"
IAP_EMAIL_HEADER = "x-goog-authenticated-user-email"
IAP_CERTS_URL = "https://www.gstatic.com/iap/verify/public_key"
IAP_ISSUER = "https://cloud.google.com/iap"


def verify_iap_jwt(token: str, audience: str) -> dict[str, Any]:
    from google.auth.transport import requests as ga_requests
    from google.oauth2 import id_token

    claims = id_token.verify_token(token, ga_requests.Request(), audience=audience, certs_url=IAP_CERTS_URL)
    if claims.get("iss") != IAP_ISSUER:
        raise ValueError("unexpected issuer")
    return claims


def resolve_user(request: Request, settings: Settings) -> UserIdentity:
    """Return the caller identity, enforcing IAP when ``REQUIRE_IAP=true``."""
    token = request.headers.get(IAP_JWT_HEADER)
    if settings.require_iap:
        if not token or not settings.iap_audience:
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Missing IAP credentials")
        try:
            claims = verify_iap_jwt(token, settings.iap_audience)
        except Exception as exc:
            logger.warning("IAP JWT rejected", extra={"error": repr(exc)})
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid IAP credentials") from exc
        return UserIdentity(user_id=str(claims["sub"]), email=claims.get("email"))
    email = request.headers.get(IAP_EMAIL_HEADER, "")
    email = email.split(":", 1)[-1] if email else None
    return UserIdentity(user_id=email or "local-dev", email=email or "local-dev")
