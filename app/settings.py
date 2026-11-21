"""Validated runtime settings for the Kaya Kopi copilot agent."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Mapping


@dataclass(frozen=True)
class AgentSettings:
    model: str
    temperature: float
    timeout_seconds: float
    max_retries: int
    max_output_tokens: int
    input_token_budget: int
    max_agent_steps: int
    tool_max_result_bytes: int

    @classmethod
    def from_env(cls, environ: Mapping[str, str] | None = None) -> "AgentSettings":
        """Build settings from environment values or safe defaults."""
        values = os.environ if environ is None else environ
        settings = cls(
            model=values.get("KAYA_OPENAI_MODEL", "gpt-4o-mini"),
            temperature=float(values.get("KAYA_LLM_TEMPERATURE", "0")),
            timeout_seconds=float(values.get("KAYA_LLM_TIMEOUT_SECONDS", "30")),
            max_retries=int(values.get("KAYA_LLM_MAX_RETRIES", "2")),
            max_output_tokens=int(values.get("KAYA_LLM_MAX_OUTPUT_TOKENS", "1000")),
            input_token_budget=int(values.get("KAYA_LLM_INPUT_TOKEN_BUDGET", "12000")),
            max_agent_steps=int(values.get("KAYA_AGENT_MAX_STEPS", "8")),
            tool_max_result_bytes=int(values.get("KAYA_TOOL_MAX_RESULT_BYTES", "30000")),
        )
        if settings.max_output_tokens <= 0:
            raise ValueError("KAYA_LLM_MAX_OUTPUT_TOKENS must be positive")
        positive_limits = {
            "KAYA_LLM_TIMEOUT_SECONDS": settings.timeout_seconds,
            "KAYA_LLM_INPUT_TOKEN_BUDGET": settings.input_token_budget,
            "KAYA_AGENT_MAX_STEPS": settings.max_agent_steps,
            "KAYA_TOOL_MAX_RESULT_BYTES": settings.tool_max_result_bytes,
        }
        for name, value in positive_limits.items():
            if value <= 0:
                raise ValueError(f"{name} must be positive")
        if settings.max_retries < 0:
            raise ValueError("KAYA_LLM_MAX_RETRIES cannot be negative")
        return settings
