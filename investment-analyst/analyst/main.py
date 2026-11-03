"""ASGI entrypoint: ``uvicorn analyst.main:app``."""

from __future__ import annotations

import os

from .api.app import create_app

app = create_app()


def run() -> None:  # pragma: no cover - process entrypoint
    import uvicorn

    uvicorn.run("analyst.main:app", host="0.0.0.0", port=int(os.environ.get("PORT", "8080")))  # noqa: S104


if __name__ == "__main__":  # pragma: no cover
    run()
