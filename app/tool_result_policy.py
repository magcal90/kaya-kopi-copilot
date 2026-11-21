"""Fail-closed size limits for model-visible tool results."""

from __future__ import annotations

import json
from typing import Any


class ToolResultPolicy:
    """Return complete results intact or replace them with an explicit limit error."""

    def __init__(self, *, max_result_bytes: int) -> None:
        if max_result_bytes <= 0:
            raise ValueError("max_result_bytes must be positive")
        self.max_result_bytes = max_result_bytes

    def enforce(self, result: dict[str, Any], *, operation: str) -> dict[str, Any]:
        """Reject an oversized result without exposing a partial payload."""
        serialized = json.dumps(
            result,
            default=str,
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
        if len(serialized) <= self.max_result_bytes:
            return result
        return {
            "ok": False,
            "error_type": "RESULT_LIMIT_EXCEEDED",
            "error": (
                f"The {operation} result is too large to send safely. "
                "Use a shorter date range, a narrower filter, or a coarser grouping."
            ),
            "complete_for_claim": False,
            "result_contract": {
                "kind": "LIMIT_EXCEEDED",
                "complete_for_claim": False,
                "truncated": False,
            },
        }
