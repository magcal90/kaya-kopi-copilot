"""Streamlit frontend for the Kaya Kopi operations copilot."""

from __future__ import annotations

import json
import logging
import sys
import uuid
from pathlib import Path
from typing import Any

# Streamlit may be launched from either the repository root or the app directory. Ensure the
# repository package root is importable in both cases before importing ``app.*`` modules.
REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

import streamlit as st
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langgraph.errors import GraphRecursionError

from app.chat_backend import get_chatbot, get_usage_tracker, retrieve_all_threads, stream_chat
from app.context_policy import ContextBudgetExceeded


st.set_page_config(page_title="Kaya Kopi Ops Copilot", page_icon="☕", layout="wide")

logger = logging.getLogger(__name__)


def _new_thread() -> str:
    return str(uuid.uuid4())


def _load_history(thread_id: str) -> list[dict[str, str]]:
    state = get_chatbot().get_state({"configurable": {"thread_id": thread_id}})
    history: list[dict[str, str]] = []
    for message in state.values.get("messages", []):
        if isinstance(message, HumanMessage):
            history.append({"role": "user", "content": str(message.content)})
        elif isinstance(message, AIMessage) and message.content:
            history.append({"role": "assistant", "content": str(message.content)})
    return history


def _text_content(content: object) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(
            str(block.get("text", "")) if isinstance(block, dict) else str(block)
            for block in content
        )
    return str(content)


if "thread_id" not in st.session_state:
    st.session_state.thread_id = _new_thread()
if "message_history" not in st.session_state:
    st.session_state.message_history = []
if "tool_log" not in st.session_state:
    st.session_state.tool_log = []


def _render_usage(panel: Any) -> None:
    try:
        summary = get_usage_tracker().budget_status(st.session_state.thread_id)
    except Exception:
        logger.exception("Unable to load LLM usage summary")
        panel.caption("LLM usage summary is temporarily unavailable.")
        return
    with panel.container():
        st.markdown("**LLM usage**")
        st.metric(
            f"Estimated spend ({summary['period']})",
            f"${summary['tracked_spend_usd']:.4f} / ${summary['budget_usd']:.2f}",
        )
        st.caption(
            f"{summary['request_count']} requests · {summary['model_call_count']} model calls · "
            f"{summary['input_tokens'] + summary['output_tokens']:,} tokens"
        )
        st.caption(f"Model: `{summary['model']}`")
        st.caption("Spend is estimated from this app's recorded usage; it excludes prior/external API use and is not a live credit balance.")
        if summary["usage_unavailable_call_count"]:
            st.warning(
                f"Usage metadata was unavailable for {summary['usage_unavailable_call_count']} "
                "successful model calls; tracked spend may be understated."
            )
        conversation = summary["conversation"]
        st.caption(
            f"This conversation: ${conversation['estimated_spend_usd']:.4f} · "
            f"{conversation['request_count']} requests · "
            f"{conversation['model_call_count']} model calls"
        )
        if summary["alert_level"] == 3:
            st.error(
                f"Estimated tracked spend has reached or exceeded the configured "
                f"USD {summary['budget_usd']:.2f} budget."
            )
        elif summary["alert_level"] == 2:
            st.error(
                f"Estimated spend reached the USD {summary['warning_usd']:.2f} budget warning threshold."
            )
        elif summary["alert_level"] == 1:
            st.warning(
                f"Estimated spend reached the USD {summary['alert_usd']:.2f} budget alert threshold."
            )

st.title("☕ Kaya Kopi Ops Copilot")
st.caption("Grounded answers from POS, invoices, operational documents, and data-quality records")

with st.sidebar:
    st.header("Conversations")
    if st.button("＋ New chat", use_container_width=True):
        st.session_state.thread_id = _new_thread()
        st.session_state.message_history = []
        st.session_state.tool_log = []
        st.rerun()

    try:
        saved_threads = retrieve_all_threads()
    except RuntimeError as error:
        st.error(str(error))
        st.stop()

    for index, thread_id in enumerate(saved_threads, start=1):
        if st.button(f"Conversation {index}", key=thread_id, use_container_width=True):
            st.session_state.thread_id = thread_id
            st.session_state.message_history = _load_history(thread_id)
            st.session_state.tool_log = []
            st.rerun()

    with st.expander("Tool activity", expanded=False):
        if not st.session_state.tool_log:
            st.caption("No tools used in this browser session yet.")
        for entry in st.session_state.tool_log:
            st.markdown(f"**{entry['name']}**")
            st.code(entry["result"], language="json")

    usage_panel = st.empty()
    _render_usage(usage_panel)

    st.divider()
    st.caption("Read-only: this assistant cannot modify the database.")

if not st.session_state.message_history:
    st.info(
        "Try: **Compare AMK-01, AMK-03 and JUR-01 sales for July 2025.**"
    )

for item in st.session_state.message_history:
    with st.chat_message(item["role"]):
        st.markdown(item["content"])

prompt = st.chat_input("Ask about sales, invoices, suppliers, documents, or data quality")
if prompt:
    st.session_state.message_history.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)

    with st.chat_message("assistant"):
        activity = {"status": None, "last_tool": "database tool"}

        def response_tokens():
            try:
                for message, _metadata in stream_chat(st.session_state.thread_id, prompt):
                    if isinstance(message, ToolMessage):
                        activity["last_tool"] = message.name or "database tool"
                        result = _text_content(message.content)
                        st.session_state.tool_log.append(
                            {"name": activity["last_tool"], "result": result}
                        )
                        if activity["status"] is None:
                            activity["status"] = st.status(
                                f"Using {activity['last_tool']}…", expanded=False
                            )
                        else:
                            activity["status"].update(
                                label=f"Using {activity['last_tool']}…"
                            )
                    elif isinstance(message, AIMessage) and message.content:
                        yield _text_content(message.content)
            except ContextBudgetExceeded:
                yield (
                    "I couldn't process that request because it exceeds the configured context "
                    "budget. Please shorten the question or start a new chat."
                )
            except GraphRecursionError:
                yield (
                    "I stopped because this request required too many tool steps. "
                    "Please narrow the question and try again."
                )
            except Exception as error:
                logger.exception(
                    "Copilot request failed",
                    extra={"thread_id": st.session_state.thread_id},
                )
                status_code = getattr(error, "status_code", None)
                if status_code is None and getattr(error, "response", None) is not None:
                    status_code = getattr(error.response, "status_code", None)
                error_code = getattr(error, "code", None)
                if status_code == 429 and error_code in {
                    "insufficient_quota", "billing_hard_limit_reached"
                }:
                    message = (
                        "The OpenAI project or billing quota has been reached. Check the "
                        "project's billing limits and available budget."
                    )
                elif status_code == 429:
                    message = (
                        "OpenAI is rate-limiting requests. The client retried transient failures; "
                        "please wait briefly and try again."
                    )
                else:
                    message = (
                        "I couldn't complete that check. The failure was logged for troubleshooting. "
                        f"Technical detail: `{type(error).__name__}`."
                    )
                yield message

        answer = st.write_stream(response_tokens())
        if activity["status"] is not None:
            activity["status"].update(
                label=f"✅ {activity['last_tool']} finished",
                state="complete",
                expanded=False,
            )

    if not isinstance(answer, str):
        answer = json.dumps(answer, default=str)
    st.session_state.message_history.append({"role": "assistant", "content": answer})
    _render_usage(usage_panel)
