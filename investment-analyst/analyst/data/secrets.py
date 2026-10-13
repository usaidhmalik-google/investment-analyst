"""Secret retrieval from Google Secret Manager (with a local-dev env override)."""

from __future__ import annotations

import logging
from functools import lru_cache

from ..config import get_settings

logger = logging.getLogger(__name__)


def access_secret(resource_name: str) -> str:
    """Read a secret version, e.g. ``projects/p/secrets/alpha-vantage-api-key/versions/latest``."""
    from google.cloud import secretmanager  # imported lazily: optional at dev time

    client = secretmanager.SecretManagerServiceClient()
    response = client.access_secret_version(name=resource_name)
    return response.payload.data.decode("utf-8").strip()


@lru_cache(maxsize=1)
def get_alpha_vantage_key() -> str | None:
    """Return the Alpha Vantage key, or ``None`` if Alpha Vantage is not configured."""
    settings = get_settings()
    if settings.alpha_vantage_api_key:
        return settings.alpha_vantage_api_key
    if settings.alpha_vantage_secret:
        try:
            return access_secret(settings.alpha_vantage_secret)
        except Exception:
            logger.exception("unable to read Alpha Vantage secret; continuing without fallback provider")
    return None
