"""Persistent, lightweight LLM usage accounting for the copilot."""

from __future__ import annotations

import json
import logging
import math
import os
import sqlite3
import threading
from contextlib import closing
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class UsageSettings:
    database_path: Path
    model: str
    input_price_per_million_usd: float = 0.15
    cached_input_price_per_million_usd: float = 0.075
    output_price_per_million_usd: float = 0.60
    budget_usd: float = 50.0
    alert_usd: float = 40.0
    warning_usd: float = 45.0

    def __post_init__(self) -> None:
        if not self.model.strip():
            raise ValueError("model must not be empty")
        prices = (
            self.input_price_per_million_usd,
            self.cached_input_price_per_million_usd,
            self.output_price_per_million_usd,
        )
        if not all(math.isfinite(price) and price >= 0 for price in prices):
            raise ValueError("LLM token prices must be finite and non-negative")
        thresholds = (self.alert_usd, self.warning_usd, self.budget_usd)
        if not all(math.isfinite(value) for value in thresholds) or not (
            0 < self.alert_usd < self.warning_usd < self.budget_usd
        ):
            raise ValueError("LLM budget thresholds must satisfy 0 < alert < warning < budget")


class LLMUsageTracker:
    """Record one row per model invocation and summarize usage by request and month."""

    def __init__(self, settings: UsageSettings) -> None:
        self.settings = settings
        self._lock = threading.RLock()
        settings.database_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.settings.database_path, timeout=10)

    def _initialize(self) -> None:
        with self._lock, closing(self._connect()) as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS llm_call_events (
                    event_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    request_id TEXT NOT NULL,
                    thread_id TEXT NOT NULL,
                    model TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    latency_ms REAL NOT NULL,
                    outcome TEXT NOT NULL,
                    http_status INTEGER,
                    error_type TEXT,
                    input_tokens INTEGER,
                    output_tokens INTEGER,
                    estimated_cost_usd REAL,
                    tool_calls_json TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_llm_call_created_at
                    ON llm_call_events(created_at);
                CREATE INDEX IF NOT EXISTS idx_llm_call_request
                    ON llm_call_events(request_id);
                CREATE INDEX IF NOT EXISTS idx_llm_call_thread
                    ON llm_call_events(thread_id, created_at);
                CREATE TABLE IF NOT EXISTS llm_request_events (
                    request_id TEXT PRIMARY KEY,
                    thread_id TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    latency_ms REAL NOT NULL,
                    outcome TEXT NOT NULL,
                    http_status INTEGER,
                    error_type TEXT,
                    model_call_count INTEGER NOT NULL,
                    tool_call_count INTEGER NOT NULL,
                    tool_calls_json TEXT NOT NULL,
                    input_tokens INTEGER,
                    output_tokens INTEGER,
                    estimated_cost_usd REAL
                );
                CREATE INDEX IF NOT EXISTS idx_llm_request_created_at
                    ON llm_request_events(created_at);
                CREATE TABLE IF NOT EXISTS llm_budget_alerts (
                    period TEXT NOT NULL,
                    threshold_usd REAL NOT NULL,
                    alerted_at TEXT NOT NULL,
                    PRIMARY KEY(period, threshold_usd)
                );
                """
            )
            connection.commit()

    @staticmethod
    def _usage_values(message: Any) -> tuple[int | None, int | None, int | None]:
        usage = getattr(message, "usage_metadata", None) or {}
        response_metadata = getattr(message, "response_metadata", None) or {}
        if not usage:
            usage = response_metadata.get("token_usage") or {}
        input_tokens = usage.get("input_tokens", usage.get("prompt_tokens"))
        output_tokens = usage.get("output_tokens", usage.get("completion_tokens"))
        details = usage.get("input_token_details") or {}
        cached_tokens = details.get("cache_read", details.get("cached_tokens", 0)) or 0
        return (
            int(input_tokens) if input_tokens is not None else None,
            int(output_tokens) if output_tokens is not None else None,
            int(cached_tokens),
        )

    @staticmethod
    def _error_details(error: BaseException | None) -> tuple[int | None, str | None, str | None]:
        if error is None:
            return None, None, None
        response = getattr(error, "response", None)
        status = getattr(error, "status_code", None) or getattr(response, "status_code", None)
        code = getattr(error, "code", None)
        return (
            int(status) if status is not None else None,
            type(error).__name__,
            str(code) if code is not None else None,
        )

    def record_model_call(
        self,
        *,
        request_id: str,
        thread_id: str,
        latency_ms: float,
        message: Any = None,
        error: BaseException | None = None,
    ) -> None:
        input_tokens: int | None = None
        output_tokens: int | None = None
        cost: float | None = None
        tool_calls: list[str] = []
        status, error_type, error_code = self._error_details(error)
        if message is not None:
            input_tokens, output_tokens, cached_tokens = self._usage_values(message)
            tool_calls = [
                str(call.get("name"))
                for call in (getattr(message, "tool_calls", None) or [])
                if call.get("name")
            ]
            if input_tokens is not None and output_tokens is not None:
                uncached_tokens = max(0, input_tokens - cached_tokens)
                cost = (
                    uncached_tokens * self.settings.input_price_per_million_usd
                    + cached_tokens * self.settings.cached_input_price_per_million_usd
                    + output_tokens * self.settings.output_price_per_million_usd
                ) / 1_000_000

        created_at = datetime.now(timezone.utc).isoformat()
        outcome = "failed" if error is not None else "succeeded"
        with self._lock, closing(self._connect()) as connection:
            connection.execute(
                """INSERT INTO llm_call_events (
                    request_id, thread_id, model, created_at, latency_ms, outcome,
                    http_status, error_type, input_tokens, output_tokens,
                    estimated_cost_usd, tool_calls_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    request_id,
                    thread_id,
                    self.settings.model,
                    created_at,
                    latency_ms,
                    outcome,
                    status,
                    error_type,
                    input_tokens,
                    output_tokens,
                    cost,
                    json.dumps(tool_calls, separators=(",", ":")),
                ),
            )
            connection.commit()

        event = {
            "event": "llm_call",
            "request_id": request_id,
            "thread_id": thread_id,
            "model": self.settings.model,
            "outcome": outcome,
            "latency_ms": round(latency_ms, 2),
            "http_status": status,
            "error_type": error_type,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "estimated_cost_usd": cost,
            "tool_calls": tool_calls,
        }
        if error is None:
            logger.info("%s", json.dumps(event, separators=(",", ":")))
        else:
            event["error_code"] = error_code
            logger.error(
                "%s",
                json.dumps(event, separators=(",", ":")),
                exc_info=(type(error), error, error.__traceback__),
            )
        self._check_budget_alerts()

    def finish_request(
        self,
        *,
        request_id: str,
        thread_id: str,
        started_at: datetime,
        latency_ms: float,
        outcome: str,
        error: BaseException | None = None,
    ) -> None:
        status, error_type, _error_code = self._error_details(error)
        with self._lock, closing(self._connect()) as connection:
            calls = connection.execute(
                """SELECT COUNT(*) AS call_count,
                          SUM(input_tokens) AS input_tokens,
                          SUM(output_tokens) AS output_tokens,
                          SUM(estimated_cost_usd) AS estimated_cost_usd,
                          GROUP_CONCAT(tool_calls_json, char(10)) AS tool_calls
                   FROM llm_call_events WHERE request_id=?""",
                (request_id,),
            ).fetchone()
            tool_names: list[str] = []
            for item in (calls[4] or "").splitlines():
                tool_names.extend(json.loads(item))
            summary = {
                "model_call_count": int(calls[0] or 0),
                "tool_call_count": len(tool_names),
                "tool_calls": tool_names,
                "input_tokens": calls[1],
                "output_tokens": calls[2],
                "estimated_cost_usd": calls[3],
            }
            connection.execute(
                """INSERT OR REPLACE INTO llm_request_events (
                    request_id, thread_id, created_at, latency_ms, outcome,
                    http_status, error_type, model_call_count, tool_call_count,
                    tool_calls_json, input_tokens, output_tokens, estimated_cost_usd
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    request_id,
                    thread_id,
                    started_at.astimezone(timezone.utc).isoformat(),
                    latency_ms,
                    outcome,
                    status,
                    error_type,
                    summary["model_call_count"],
                    summary["tool_call_count"],
                    json.dumps(tool_names, separators=(",", ":")),
                    summary["input_tokens"],
                    summary["output_tokens"],
                    summary["estimated_cost_usd"],
                ),
            )
            connection.commit()
        logger.info(
            "%s",
            json.dumps(
                {
                    "event": "llm_request",
                    "request_id": request_id,
                    "thread_id": thread_id,
                    "outcome": outcome,
                    "latency_ms": round(latency_ms, 2),
                    "http_status": status,
                    "error_type": error_type,
                    **summary,
                },
                separators=(",", ":"),
            ),
        )

    def _period_start(self) -> datetime:
        now = datetime.now(timezone.utc)
        return now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

    def _check_budget_alerts(self) -> None:
        period_start = self._period_start()
        period = period_start.strftime("%Y-%m")
        with self._lock, closing(self._connect()) as connection:
            spend = float(
                connection.execute(
                    "SELECT COALESCE(SUM(estimated_cost_usd), 0) FROM llm_call_events WHERE created_at >= ?",
                    (period_start.isoformat(),),
                ).fetchone()[0]
                or 0
            )
            for threshold in (
                self.settings.alert_usd,
                self.settings.warning_usd,
                self.settings.budget_usd,
            ):
                if spend >= threshold:
                    cursor = connection.execute(
                        "INSERT OR IGNORE INTO llm_budget_alerts(period, threshold_usd, alerted_at) VALUES (?, ?, ?)",
                        (period, threshold, datetime.now(timezone.utc).isoformat()),
                    )
                    if cursor.rowcount:
                        logger.warning(
                            "%s",
                            json.dumps(
                                {
                                    "event": "llm_budget_alert",
                                    "period": period,
                                    "tracked_spend_usd": round(spend, 6),
                                    "threshold_usd": threshold,
                                    "budget_usd": self.settings.budget_usd,
                                },
                                separators=(",", ":"),
                            ),
                        )
            connection.commit()

    def budget_status(self, thread_id: str | None = None) -> dict[str, Any]:
        period_start = self._period_start()
        with self._lock, closing(self._connect()) as connection:
            month = connection.execute(
                """SELECT COUNT(*), SUM(input_tokens), SUM(output_tokens),
                          SUM(estimated_cost_usd),
                          SUM(outcome='succeeded' AND estimated_cost_usd IS NULL)
                   FROM llm_call_events WHERE created_at >= ?""",
                (period_start.isoformat(),),
            ).fetchone()
            month_requests = connection.execute(
                "SELECT COUNT(*) FROM llm_request_events WHERE created_at >= ?",
                (period_start.isoformat(),),
            ).fetchone()[0]
            conversation = None
            if thread_id is not None:
                conversation = connection.execute(
                    """SELECT COUNT(*), SUM(input_tokens), SUM(output_tokens),
                              SUM(estimated_cost_usd),
                              SUM(outcome='succeeded' AND estimated_cost_usd IS NULL)
                       FROM llm_call_events WHERE thread_id=?""",
                    (thread_id,),
                ).fetchone()
                conversation_requests = connection.execute(
                    "SELECT COUNT(*) FROM llm_request_events WHERE thread_id=?",
                    (thread_id,),
                ).fetchone()[0]
            else:
                conversation_requests = 0

        spend = float(month[3] or 0)
        alert_level = (
            3 if spend >= self.settings.budget_usd
            else 2 if spend >= self.settings.warning_usd
            else 1 if spend >= self.settings.alert_usd
            else 0
        )
        status = {
            "period": period_start.strftime("%Y-%m UTC"),
            "model": self.settings.model,
            "budget_usd": self.settings.budget_usd,
            "alert_usd": self.settings.alert_usd,
            "warning_usd": self.settings.warning_usd,
            "tracked_spend_usd": spend,
            "remaining_estimated_budget_usd": max(0.0, self.settings.budget_usd - spend),
            "alert_level": alert_level,
            "request_count": int(month_requests or 0),
            "model_call_count": int(month[0] or 0),
            "input_tokens": int(month[1] or 0),
            "output_tokens": int(month[2] or 0),
            "usage_unavailable_call_count": int(month[4] or 0),
        }
        if conversation is not None:
            status["conversation"] = {
                "request_count": int(conversation_requests or 0),
                "model_call_count": int(conversation[0] or 0),
                "input_tokens": int(conversation[1] or 0),
                "output_tokens": int(conversation[2] or 0),
                "estimated_spend_usd": float(conversation[3] or 0),
                "usage_unavailable_call_count": int(conversation[4] or 0),
            }
        return status


def usage_settings_from_env(model: str) -> UsageSettings:
    database_path = Path(os.getenv("KAYA_USAGE_DB", "runtime/kaya_usage.sqlite3"))
    return UsageSettings(
        database_path=database_path,
        model=model,
        input_price_per_million_usd=float(os.getenv("KAYA_LLM_INPUT_PRICE_PER_1M_USD", "0.15")),
        cached_input_price_per_million_usd=float(os.getenv("KAYA_LLM_CACHED_INPUT_PRICE_PER_1M_USD", "0.075")),
        output_price_per_million_usd=float(os.getenv("KAYA_LLM_OUTPUT_PRICE_PER_1M_USD", "0.60")),
        budget_usd=float(os.getenv("KAYA_LLM_BUDGET_USD", "50")),
        alert_usd=float(os.getenv("KAYA_LLM_BUDGET_ALERT_USD", "40")),
        warning_usd=float(os.getenv("KAYA_LLM_BUDGET_WARNING_USD", "45")),
    )
