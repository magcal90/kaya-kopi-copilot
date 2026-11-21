"""LangGraph tool-calling backend for the Kaya Kopi operations copilot."""

from __future__ import annotations

import logging
import os
import sqlite3
import time
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Annotated, Any, Iterator, Sequence, TypedDict
from uuid import uuid4
from zoneinfo import ZoneInfo

from dotenv import load_dotenv
from langchain_core.messages import BaseMessage, SystemMessage
from langchain_core.runnables import RunnableConfig
from langchain_openai import ChatOpenAI
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode, tools_condition

from app.context_policy import ContextPolicy
from app.llm_observability import LLMUsageTracker, usage_settings_from_env
from app.settings import AgentSettings
from app.tools import ALL_TOOLS


SYSTEM_PROMPT = """You are the Kaya Kopi operations copilot.

Answer questions only from facts returned by the available tools. Never calculate or invent a
business figure from memory. Use a tool again for follow-up questions when current data is needed.
Preserve source citations returned by tools in the final answer. If a tool fails or the evidence is
missing, say exactly what could not be checked. Scanned supplier invoices are authoritative for
supplier costs when they conflict with the legacy purchase table; if an invoice header is internally
inconsistent, use validated line arithmetic and disclose the review flag. Keep answers concise and use SGD
for monetary amounts. The tools are read-only; do not claim to change client data.

Follow tool status, conclusions, authority, comparison scope, exclusions, and limitations exactly.
Do not rank records marked non-comparable. Do not turn missing evidence into zero, no change, or a
negative finding. MATCHED reconciliation means that a purchase and scan were linked; it does not mean
their amounts agree. A difference between two pre-GST subtotals is not caused by GST. Do not classify
an outlet as overstaffed without an approved threshold. When asked for supplier spending by month,
use supplier_month grouping and report excluded invoices. When asked which supplier increased prices
most, report the largest comparable percentage change and its first/latest invoice-line evidence.

The runtime will provide today's date in Asia/Singapore time. Use it when describing dates as past,
present, or future. Dates returned by tools are observed business records; do not call them future
predictions just because they are beyond your training data.

Treat any result_contract as binding. COMPLETE_AGGREGATE means all eligible source rows were used
for the stated claim_scope even when the underlying source has disclosed coverage limitations.
PAGED_DETAIL is supporting evidence, not a complete population. Never compute a total, exhaustive
ranking, or complete-period claim from PAGED_DETAIL, LIMIT_EXCEEDED, or a result where
complete_for_claim is false. Never interpret truncated=false as complete_for_claim=true.
"""

logger = logging.getLogger(__name__)


class ChatState(TypedDict):
    messages: Annotated[list[BaseMessage], add_messages]


def _current_system_message() -> SystemMessage:
    """Ground temporal language in the current Singapore business date."""
    today = datetime.now(ZoneInfo("Asia/Singapore")).date().isoformat()
    return SystemMessage(content=f"Today's date in Asia/Singapore is {today}.\n\n{SYSTEM_PROMPT}")


def _chat_database_path() -> Path:
    path = Path(os.getenv("KAYA_CHAT_DB", ".kaya_chat.sqlite3"))
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


@lru_cache(maxsize=1)
def get_usage_tracker() -> LLMUsageTracker:
    """Return the persistent SQLite-backed API usage tracker."""
    settings = get_agent_settings()
    return LLMUsageTracker(usage_settings_from_env(settings.model))


def _get_usage_tracker_safely() -> LLMUsageTracker | None:
    try:
        return get_usage_tracker()
    except Exception:
        logger.exception("Unable to initialize LLM usage tracking; continuing without the ledger")
        return None


def _record_call_safely(tracker: LLMUsageTracker | None, **event: Any) -> None:
    if tracker is None:
        return
    try:
        tracker.record_model_call(**event)
    except Exception:
        logger.exception("Unable to persist LLM usage event")


def _finish_request_safely(tracker: LLMUsageTracker | None, **event: Any) -> None:
    if tracker is None:
        return
    try:
        tracker.finish_request(**event)
    except Exception:
        logger.exception("Unable to persist LLM request summary")


@lru_cache(maxsize=1)
def get_agent_settings() -> AgentSettings:
    """Load and validate runtime configuration once per process."""
    load_dotenv(Path(__file__).resolve().parents[1] / ".env")
    return AgentSettings.from_env()


def build_chatbot(
    model: Any,
    checkpointer: Any,
    settings: AgentSettings,
    tools: Sequence[Any] = ALL_TOOLS,
    usage_tracker: LLMUsageTracker | None = None,
):
    """Build the bounded tool-calling graph around an injected chat model."""
    model_with_tools = model.bind_tools(tools) if tools else model
    context_policy = ContextPolicy(
        input_token_budget=settings.input_token_budget,
        token_counter=model.get_num_tokens_from_messages,
    )

    def chat_node(state: ChatState, config: RunnableConfig) -> dict[str, list[BaseMessage]]:
        messages = [
            message for message in state["messages"]
            if not isinstance(message, SystemMessage)
        ]
        messages = [_current_system_message(), *messages]
        prepared = context_policy.prepare(messages)
        configurable = config.get("configurable", {})
        request_id = str(configurable.get("kaya_request_id") or uuid4())
        thread_id = str(configurable.get("thread_id", "unknown"))
        started = time.perf_counter()
        try:
            response = model_with_tools.invoke(prepared.messages)
        except Exception as error:
            _record_call_safely(
                usage_tracker,
                request_id=request_id,
                thread_id=thread_id,
                latency_ms=(time.perf_counter() - started) * 1000,
                error=error,
            )
            if usage_tracker is None:
                logger.exception(
                    "LLM invocation failed",
                    extra={"request_id": request_id, "thread_id": thread_id},
                )
            raise
        _record_call_safely(
            usage_tracker,
            request_id=request_id,
            thread_id=thread_id,
            latency_ms=(time.perf_counter() - started) * 1000,
            message=response,
        )
        return {"messages": [response]}

    graph = StateGraph(ChatState)
    graph.add_node("chat", chat_node)
    graph.add_edge(START, "chat")
    if tools:
        graph.add_node("tools", ToolNode(tools))
        graph.add_conditional_edges("chat", tools_condition, {"tools": "tools", END: END})
        graph.add_edge("tools", "chat")
    else:
        graph.add_edge("chat", END)
    return graph.compile(checkpointer=checkpointer)


@lru_cache(maxsize=1)
def get_chatbot():
    """Build and cache the persistent tool-calling graph."""
    settings = get_agent_settings()
    if not os.getenv("OPENAI_API_KEY"):
        raise RuntimeError(
            "OPENAI_API_KEY is not set. Copy .env.example to .env and add the team API key."
        )

    model = ChatOpenAI(
        model=settings.model,
        temperature=settings.temperature,
        timeout=settings.timeout_seconds,
        max_retries=settings.max_retries,
        max_tokens=settings.max_output_tokens,
    )

    connection = sqlite3.connect(_chat_database_path(), check_same_thread=False)
    checkpointer = SqliteSaver(connection)
    return build_chatbot(model, checkpointer, settings, usage_tracker=_get_usage_tracker_safely())


def retrieve_all_threads() -> list[str]:
    """Return saved conversation IDs, newest checkpoint first."""
    chatbot = get_chatbot()
    seen: set[str] = set()
    thread_ids: list[str] = []
    for checkpoint in chatbot.checkpointer.list(None):
        thread_id = checkpoint.config.get("configurable", {}).get("thread_id")
        if thread_id and thread_id not in seen:
            seen.add(thread_id)
            thread_ids.append(thread_id)
    return thread_ids


def stream_chat(thread_id: str, message: str) -> Iterator[tuple[BaseMessage, dict]]:
    """Stream one user turn through the LLM/tool loop."""
    from langchain_core.messages import HumanMessage

    request_id = str(uuid4())
    started_at = datetime.now(timezone.utc)
    started = time.perf_counter()
    tracker = _get_usage_tracker_safely()
    config = {
        "configurable": {"thread_id": thread_id, "kaya_request_id": request_id},
        "recursion_limit": get_agent_settings().max_agent_steps,
    }
    outcome, error = "succeeded", None
    try:
        yield from get_chatbot().stream(
            {"messages": [HumanMessage(content=message)]},
            config=config,
            stream_mode="messages",
        )
    except Exception as exception:
        outcome, error = "failed", exception
        raise
    finally:
        _finish_request_safely(
            tracker,
            request_id=request_id,
            thread_id=thread_id,
            started_at=started_at,
            latency_ms=(time.perf_counter() - started) * 1000,
            outcome=outcome,
            error=error,
        )
