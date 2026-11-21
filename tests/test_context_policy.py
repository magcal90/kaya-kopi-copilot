"""Behavioral tests for bounded conversation context."""

from __future__ import annotations

import unittest

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

from app.context_policy import ContextBudgetExceeded, ContextPolicy


class ContextPolicyTest(unittest.TestCase):
    def test_latest_user_turn_and_system_prompt_are_kept_within_budget(self) -> None:
        messages = [
            SystemMessage(content="system"),
            HumanMessage(content="old question"),
            AIMessage(content="old answer"),
            HumanMessage(content="current question"),
        ]
        policy = ContextPolicy(
            input_token_budget=2,
            token_counter=lambda selected: len(selected),
        )

        prepared = policy.prepare(messages)

        self.assertEqual(prepared.messages, [messages[0], messages[3]])
        self.assertEqual(prepared.estimated_tokens, 2)
        self.assertEqual(prepared.omitted_messages, 2)
        self.assertTrue(prepared.compacted)

    def test_required_current_turn_larger_than_budget_is_rejected(self) -> None:
        messages = [
            SystemMessage(content="system"),
            HumanMessage(content="current question"),
        ]
        policy = ContextPolicy(
            input_token_budget=1,
            token_counter=lambda selected: len(selected),
        )

        with self.assertRaisesRegex(ContextBudgetExceeded, "current request exceeds"):
            policy.prepare(messages)

    def test_prior_tool_exchange_is_kept_as_a_complete_turn(self) -> None:
        prior_user = HumanMessage(content="old question")
        prior_assistant = AIMessage(
            content="",
            tool_calls=[{"name": "lookup", "args": {}, "id": "call-1"}],
        )
        prior_tool = ToolMessage(content="evidence", tool_call_id="call-1")
        current_user = HumanMessage(content="current question")
        messages = [
            SystemMessage(content="system"),
            prior_user,
            prior_assistant,
            prior_tool,
            current_user,
        ]
        policy = ContextPolicy(
            input_token_budget=5,
            token_counter=lambda selected: len(selected),
        )

        prepared = policy.prepare(messages)

        self.assertEqual(prepared.messages, messages)
        self.assertFalse(prepared.compacted)

    def test_oversized_active_tool_result_is_rejected_before_another_model_call(self) -> None:
        messages = [
            SystemMessage(content="system"),
            HumanMessage(content="current question"),
            AIMessage(
                content="",
                tool_calls=[{"name": "lookup", "args": {}, "id": "call-1"}],
            ),
            ToolMessage(content="x" * 100, tool_call_id="call-1"),
        ]
        policy = ContextPolicy(
            input_token_budget=50,
            token_counter=lambda selected: sum(len(str(message.content)) for message in selected),
        )

        with self.assertRaisesRegex(ContextBudgetExceeded, "current request exceeds"):
            policy.prepare(messages)


if __name__ == "__main__":
    unittest.main()
