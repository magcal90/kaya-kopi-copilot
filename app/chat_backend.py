"""LangGraph tool-calling backend for the Kaya Kopi operations copilot."""

from __future__ import annotations

import os
import sqlite3
from functools import lru_cache
from pathlib import Path
from typing import Annotated, Iterator, TypedDict

from dotenv import load_dotenv
from langchain_core.messages import BaseMessage, SystemMessage
from langchain_openai import ChatOpenAI
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode, tools_condition

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
"""


class ChatState(TypedDict):
    messages: Annotated[list[BaseMessage], add_messages]


def _chat_database_path() -> Path:
    path = Path(os.getenv("KAYA_CHAT_DB", ".kaya_chat.sqlite3"))
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


@lru_cache(maxsize=1)
def get_chatbot():
    """Build and cache the persistent tool-calling graph."""
    load_dotenv(Path(__file__).resolve().parents[1] / ".env")
    if not os.getenv("OPENAI_API_KEY"):
        raise RuntimeError(
            "OPENAI_API_KEY is not set. Copy .env.example to .env and add the team API key."
        )

    model = ChatOpenAI(
        model=os.getenv("KAYA_OPENAI_MODEL", "gpt-4o-mini"),
        temperature=0,
        timeout=30,
        max_retries=2,
    )
    model_with_tools = model.bind_tools(ALL_TOOLS)

    def chat_node(state: ChatState) -> dict[str, list[BaseMessage]]:
        messages = state["messages"]
        if not messages or not isinstance(messages[0], SystemMessage):
            messages = [SystemMessage(content=SYSTEM_PROMPT), *messages]
        return {"messages": [model_with_tools.invoke(messages)]}

    connection = sqlite3.connect(_chat_database_path(), check_same_thread=False)
    checkpointer = SqliteSaver(connection)
    graph = StateGraph(ChatState)
    graph.add_node("chat", chat_node)
    graph.add_node("tools", ToolNode(ALL_TOOLS))
    graph.add_edge(START, "chat")
    graph.add_conditional_edges("chat", tools_condition, {"tools": "tools", END: END})
    graph.add_edge("tools", "chat")
    return graph.compile(checkpointer=checkpointer)


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

    config = {"configurable": {"thread_id": thread_id}}
    yield from get_chatbot().stream(
        {"messages": [HumanMessage(content=message)]},
        config=config,
        stream_mode="messages",
    )
