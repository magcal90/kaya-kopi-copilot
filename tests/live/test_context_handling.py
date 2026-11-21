"""Opt-in acceptance test against the real OpenAI API.

Run explicitly with:
    KAYA_RUN_LIVE_LLM_TESTS=1 python -m unittest tests.live.test_context_handling -v
"""

from __future__ import annotations

import os
import unittest
from dataclasses import replace
from pathlib import Path
from uuid import uuid4

from dotenv import load_dotenv
from langchain_core.messages import AIMessage, HumanMessage
from langchain_openai import ChatOpenAI
from langgraph.checkpoint.memory import MemorySaver

from app.chat_backend import build_chatbot
from app.settings import AgentSettings


LIVE_TESTS_ENABLED = os.getenv("KAYA_RUN_LIVE_LLM_TESTS") == "1"


@unittest.skipUnless(LIVE_TESTS_ENABLED, "set KAYA_RUN_LIVE_LLM_TESTS=1 to use OpenAI")
class LiveContextHandlingTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        load_dotenv(Path(__file__).resolve().parents[2] / ".env")
        if not os.getenv("OPENAI_API_KEY"):
            raise unittest.SkipTest("OPENAI_API_KEY is not configured in .env")

    def test_real_openai_graph_returns_usage_with_bounded_output(self) -> None:
        settings = replace(
            AgentSettings.from_env(),
            max_output_tokens=32,
            input_token_budget=2_000,
            max_agent_steps=4,
            max_retries=0,
        )
        model = ChatOpenAI(
            model=settings.model,
            temperature=settings.temperature,
            timeout=settings.timeout_seconds,
            max_retries=settings.max_retries,
            max_tokens=settings.max_output_tokens,
        )
        chatbot = build_chatbot(model, MemorySaver(), settings, tools=())

        result = chatbot.invoke(
            {"messages": [HumanMessage(content="Reply with exactly: LIVE_OK")]},
            config={
                "configurable": {"thread_id": f"live-context-{uuid4()}"},
                "recursion_limit": settings.max_agent_steps,
            },
        )

        responses = [message for message in result["messages"] if isinstance(message, AIMessage)]
        self.assertTrue(responses)
        usage = responses[-1].usage_metadata
        self.assertIsNotNone(usage)
        self.assertGreater(usage.get("input_tokens", 0), 0)
        self.assertGreater(usage.get("output_tokens", 0), 0)
        self.assertLessEqual(usage["output_tokens"], settings.max_output_tokens)


if __name__ == "__main__":
    unittest.main()
