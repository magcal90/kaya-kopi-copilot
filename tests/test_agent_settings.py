"""Behavioral tests for agent runtime configuration."""

from __future__ import annotations

import unittest

from app.settings import AgentSettings


class AgentSettingsTest(unittest.TestCase):
    def test_defaults_are_safe_for_the_copilot_runtime(self) -> None:
        settings = AgentSettings.from_env({})

        self.assertEqual(settings.model, "gpt-4o-mini")
        self.assertEqual(settings.temperature, 0)
        self.assertEqual(settings.timeout_seconds, 30)
        self.assertEqual(settings.max_retries, 2)
        self.assertEqual(settings.max_output_tokens, 1_000)
        self.assertEqual(settings.input_token_budget, 12_000)
        self.assertEqual(settings.max_agent_steps, 8)
        self.assertEqual(settings.tool_max_result_bytes, 30_000)

    def test_environment_overrides_runtime_limits(self) -> None:
        settings = AgentSettings.from_env(
            {
                "KAYA_OPENAI_MODEL": "gpt-4.1-mini",
                "KAYA_LLM_TEMPERATURE": "0.2",
                "KAYA_LLM_TIMEOUT_SECONDS": "45",
                "KAYA_LLM_MAX_RETRIES": "1",
                "KAYA_LLM_MAX_OUTPUT_TOKENS": "750",
                "KAYA_LLM_INPUT_TOKEN_BUDGET": "9000",
                "KAYA_AGENT_MAX_STEPS": "6",
                "KAYA_TOOL_MAX_RESULT_BYTES": "24000",
            }
        )

        self.assertEqual(settings.model, "gpt-4.1-mini")
        self.assertEqual(settings.temperature, 0.2)
        self.assertEqual(settings.timeout_seconds, 45)
        self.assertEqual(settings.max_retries, 1)
        self.assertEqual(settings.max_output_tokens, 750)
        self.assertEqual(settings.input_token_budget, 9_000)
        self.assertEqual(settings.max_agent_steps, 6)
        self.assertEqual(settings.tool_max_result_bytes, 24_000)

    def test_non_positive_output_limit_is_rejected_at_startup(self) -> None:
        with self.assertRaisesRegex(ValueError, "KAYA_LLM_MAX_OUTPUT_TOKENS must be positive"):
            AgentSettings.from_env({"KAYA_LLM_MAX_OUTPUT_TOKENS": "0"})

    def test_non_positive_runtime_limits_are_rejected_at_startup(self) -> None:
        invalid_values = {
            "KAYA_LLM_TIMEOUT_SECONDS": "0",
            "KAYA_LLM_INPUT_TOKEN_BUDGET": "0",
            "KAYA_AGENT_MAX_STEPS": "0",
        }
        for name, value in invalid_values.items():
            with self.subTest(name=name):
                with self.assertRaisesRegex(ValueError, f"{name} must be positive"):
                    AgentSettings.from_env({name: value})

    def test_negative_retry_count_is_rejected_at_startup(self) -> None:
        with self.assertRaisesRegex(ValueError, "KAYA_LLM_MAX_RETRIES cannot be negative"):
            AgentSettings.from_env({"KAYA_LLM_MAX_RETRIES": "-1"})


if __name__ == "__main__":
    unittest.main()
