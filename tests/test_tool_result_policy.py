"""Behavioral tests for model-visible tool result limits."""

from __future__ import annotations

import unittest

from app.tool_result_policy import ToolResultPolicy


class ToolResultPolicyTest(unittest.TestCase):
    def test_oversized_complete_aggregate_fails_closed_without_partial_rows(self) -> None:
        result = {
            "ok": True,
            "results": [{"month": "2025-01", "total_sgd": "123.45", "detail": "x" * 200}],
            "result_contract": {
                "kind": "COMPLETE_AGGREGATE",
                "complete_for_claim": True,
                "truncated": False,
            },
        }
        policy = ToolResultPolicy(max_result_bytes=100)

        enforced = policy.enforce(result, operation="analyze_suppliers")

        self.assertEqual(enforced["ok"], False)
        self.assertEqual(enforced["error_type"], "RESULT_LIMIT_EXCEEDED")
        self.assertEqual(enforced["complete_for_claim"], False)
        self.assertNotIn("results", enforced)
        self.assertEqual(
            enforced["result_contract"],
            {
                "kind": "LIMIT_EXCEEDED",
                "complete_for_claim": False,
                "truncated": False,
            },
        )


if __name__ == "__main__":
    unittest.main()
