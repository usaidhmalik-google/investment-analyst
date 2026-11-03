"""Usage/cost telemetry and access audit trail (structured logs + optional BigQuery sink).

Rows match the ``analyst_telemetry.usage_events`` and ``analyst_telemetry.audit_log``
tables provisioned in ``terraform/analyst/bigquery.tf``.
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import UTC, datetime
from typing import Any

from ..config import Settings

logger = logging.getLogger("analyst.telemetry")


class TelemetrySink:
    def __init__(self, settings: Settings, bq_client: Any | None = None) -> None:
        self.usage_table = settings.bq_usage_table
        self.audit_table = settings.bq_audit_table
        self._client = bq_client
        self._project = settings.google_cloud_project
        self._pending: set[asyncio.Task] = set()

    def _bq(self) -> Any:
        if self._client is None:  # pragma: no cover - requires GCP credentials
            from google.cloud import bigquery

            self._client = bigquery.Client(project=self._project)
        return self._client

    def _insert(self, table: str, row: dict[str, Any]) -> None:
        errors = self._bq().insert_rows_json(table, [row])
        if errors:
            logger.error("bigquery insert failed", extra={"table": table, "errors": errors})

    def _fire(self, table: str | None, row: dict[str, Any]) -> None:
        if not table:
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            self._insert(table, row)
            return
        task = loop.create_task(asyncio.to_thread(self._insert, table, row))
        self._pending.add(task)
        task.add_done_callback(self._pending.discard)

    def record_usage(
        self,
        *,
        session_id: str,
        report_id: str,
        user: str,
        model: str,
        agent: str,
        usage: dict[str, int],
        ttft_ms: float | None,
        total_ms: float,
        tools_called: list[dict[str, Any]],
        tickers: list[str],
    ) -> None:
        row = {
            "ts": datetime.now(UTC).isoformat(),
            "session_id": session_id,
            "report_id": report_id,
            "user": user,
            "model": model,
            "agent": agent,
            "prompt_tokens": usage.get("prompt_tokens", 0),
            "output_tokens": usage.get("output_tokens", 0),
            "total_tokens": usage.get("total_tokens", 0),
            "ttft_ms": ttft_ms,
            "total_ms": total_ms,
            "tools_called": json.dumps(tools_called, default=str),
            "tickers": tickers,
        }
        logger.info("usage", extra={"telemetry": row})
        self._fire(self.usage_table, row)

    def record_audit(
        self, *, user: str, action: str, tickers: list[str], session_id: str | None, report_id: str | None, status: str
    ) -> None:
        row = {
            "ts": datetime.now(UTC).isoformat(),
            "user": user,
            "action": action,
            "tickers": tickers,
            "session_id": session_id,
            "report_id": report_id,
            "status": status,
        }
        logger.info("audit", extra={"audit": row})
        self._fire(self.audit_table, row)

    async def drain(self) -> None:
        if self._pending:
            await asyncio.gather(*self._pending, return_exceptions=True)
