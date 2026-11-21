"""Tests for local usage persistence and spend estimates; these do not call an LLM."""

from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

from app.llm_observability import LLMUsageTracker, UsageSettings


class LLMUsageTrackerTest(unittest.TestCase):
    def _tracker(self, directory: str, **overrides: float) -> LLMUsageTracker:
        values = {
            "input_price_per_million_usd": 1.0,
            "cached_input_price_per_million_usd": 0.5,
            "output_price_per_million_usd": 2.0,
            "budget_usd": 50.0,
            "alert_usd": 40.0,
            "warning_usd": 45.0,
        }
        values.update(overrides)
        return LLMUsageTracker(
            UsageSettings(database_path=Path(directory) / "usage.sqlite3", model="test-model", **values)
        )

    def test_records_usage_cost_latency_tools_and_conversation_totals(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            tracker = self._tracker(directory)
            response = SimpleNamespace(
                usage_metadata={
                    "input_tokens": 100,
                    "output_tokens": 10,
                    "input_token_details": {"cached_tokens": 20},
                },
                response_metadata={},
                tool_calls=[{"name": "analyze_outlets"}],
            )
            tracker.record_model_call(
                request_id="request-1",
                thread_id="thread-1",
                latency_ms=125.5,
                message=response,
            )
            tracker.finish_request(
                request_id="request-1",
                thread_id="thread-1",
                started_at=datetime.now(timezone.utc),
                latency_ms=500,
                outcome="succeeded",
            )

            summary = tracker.budget_status("thread-1")
            self.assertEqual(summary["model_call_count"], 1)
            self.assertEqual(summary["input_tokens"], 100)
            self.assertEqual(summary["output_tokens"], 10)
            self.assertAlmostEqual(summary["tracked_spend_usd"], 0.00011)
            self.assertEqual(summary["conversation"]["request_count"], 1)
            self.assertAlmostEqual(summary["conversation"]["estimated_spend_usd"], 0.00011)

            with sqlite3.connect(Path(directory) / "usage.sqlite3") as connection:
                request = connection.execute(
                    "SELECT tool_call_count, tool_calls_json, latency_ms FROM llm_request_events"
                ).fetchone()
            self.assertEqual(request[0], 1)
            self.assertEqual(json.loads(request[1]), ["analyze_outlets"])
            self.assertEqual(request[2], 500)

    def test_records_429_status_and_error_type(self) -> None:
        class RateLimitError(Exception):
            status_code = 429
            code = "rate_limit_exceeded"

        with tempfile.TemporaryDirectory() as directory:
            tracker = self._tracker(directory)
            error = RateLimitError("limited")
            tracker.record_model_call(
                request_id="request-2",
                thread_id="thread-2",
                latency_ms=200,
                error=error,
            )
            with sqlite3.connect(Path(directory) / "usage.sqlite3") as connection:
                row = connection.execute(
                    "SELECT outcome, http_status, error_type FROM llm_call_events"
                ).fetchone()
            self.assertEqual(row, ("failed", 429, "RateLimitError"))

    def test_budget_status_crosses_configured_alert_thresholds(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            tracker = self._tracker(
                directory,
                input_price_per_million_usd=1_000_000,
                cached_input_price_per_million_usd=1_000_000,
                output_price_per_million_usd=0,
            )
            response = SimpleNamespace(
                usage_metadata={"input_tokens": 50, "output_tokens": 0},
                response_metadata={},
                tool_calls=[],
            )
            tracker.record_model_call(
                request_id="request-3",
                thread_id="thread-3",
                latency_ms=1,
                message=response,
            )
            self.assertEqual(tracker.budget_status()["alert_level"], 3)
            with sqlite3.connect(Path(directory) / "usage.sqlite3") as connection:
                alert_count = connection.execute("SELECT COUNT(*) FROM llm_budget_alerts").fetchone()[0]
            self.assertEqual(alert_count, 3)

    def test_rejects_out_of_order_budget_thresholds(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(ValueError):
                UsageSettings(
                    database_path=Path(directory) / "usage.sqlite3",
                    model="test-model",
                    alert_usd=45,
                    warning_usd=40,
                    budget_usd=50,
                )


if __name__ == "__main__":
    unittest.main()
