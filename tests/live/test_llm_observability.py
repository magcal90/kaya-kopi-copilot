"""Opt-in OpenAI integration test for usage capture on a real copilot request."""

from __future__ import annotations

import os
import unittest
from pathlib import Path
from uuid import uuid4

from dotenv import load_dotenv
from langchain_core.messages import AIMessage

from app.chat_backend import get_usage_tracker, stream_chat


LIVE_TESTS_ENABLED = os.getenv("KAYA_RUN_LIVE_LLM_TESTS") == "1"


@unittest.skipUnless(LIVE_TESTS_ENABLED, "set KAYA_RUN_LIVE_LLM_TESTS=1 to use OpenAI")
class LiveLLMObservabilityTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        load_dotenv(Path(__file__).resolve().parents[2] / ".env")
        if not os.getenv("OPENAI_API_KEY"):
            raise unittest.SkipTest("OPENAI_API_KEY is not configured in .env")

    def test_real_openai_usage_is_written_to_the_usage_ledger(self) -> None:
        thread_id = f"live-usage-{uuid4()}"
        messages = list(stream_chat(thread_id, "Reply with exactly: USAGE_CAPTURED"))
        answers = [
            message.content
            for message, _metadata in messages
            if isinstance(message, AIMessage) and message.content
        ]
        self.assertTrue(answers)
        summary = get_usage_tracker().budget_status(thread_id)["conversation"]
        self.assertEqual(summary["request_count"], 1)
        self.assertGreaterEqual(summary["model_call_count"], 1)
        self.assertGreater(summary["input_tokens"], 0)
        self.assertGreater(summary["output_tokens"], 0)
        self.assertGreater(summary["estimated_spend_usd"], 0)


if __name__ == "__main__":
    unittest.main()
