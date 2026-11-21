"""Token-aware selection of conversation messages sent to the LLM."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass

from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage


class ContextBudgetExceeded(ValueError):
    """Raised when the required current turn cannot fit the input budget."""


@dataclass(frozen=True)
class PreparedContext:
    messages: list[BaseMessage]
    estimated_tokens: int
    omitted_messages: int
    compacted: bool


class ContextPolicy:
    """Keep the current turn and as much recent complete history as fits."""

    def __init__(
        self,
        *,
        input_token_budget: int,
        token_counter: Callable[[Sequence[BaseMessage]], int],
    ) -> None:
        if input_token_budget <= 0:
            raise ValueError("input_token_budget must be positive")
        self.input_token_budget = input_token_budget
        self.token_counter = token_counter

    def prepare(self, messages: Sequence[BaseMessage]) -> PreparedContext:
        """Return a bounded prompt without splitting prior conversation turns."""
        all_messages = list(messages)
        leading_system: list[BaseMessage] = []
        conversation = list(all_messages)
        while conversation and isinstance(conversation[0], SystemMessage):
            leading_system.append(conversation.pop(0))

        latest_human = next(
            (
                index
                for index in range(len(conversation) - 1, -1, -1)
                if isinstance(conversation[index], HumanMessage)
            ),
            0,
        )
        history = conversation[:latest_human]
        current_turn = conversation[latest_human:]
        required = [*leading_system, *current_turn]
        required_tokens = self.token_counter(required)
        if required_tokens > self.input_token_budget:
            raise ContextBudgetExceeded(
                "The current request exceeds the configured LLM input token budget."
            )

        selected_history: list[BaseMessage] = []
        for turn in reversed(self._turns(history)):
            candidate = [*leading_system, *turn, *selected_history, *current_turn]
            if self.token_counter(candidate) > self.input_token_budget:
                break
            selected_history = [*turn, *selected_history]

        selected = [*leading_system, *selected_history, *current_turn]
        estimated_tokens = self.token_counter(selected)
        omitted_messages = len(all_messages) - len(selected)
        return PreparedContext(
            messages=selected,
            estimated_tokens=estimated_tokens,
            omitted_messages=omitted_messages,
            compacted=omitted_messages > 0,
        )

    @staticmethod
    def _turns(messages: Sequence[BaseMessage]) -> list[list[BaseMessage]]:
        turns: list[list[BaseMessage]] = []
        for message in messages:
            if isinstance(message, HumanMessage) or not turns:
                turns.append([])
            turns[-1].append(message)
        return turns
