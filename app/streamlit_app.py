"""Streamlit frontend for the Kaya Kopi operations copilot."""

from __future__ import annotations

import json
import sys
import uuid
from pathlib import Path

# Streamlit may be launched from either the repository root or the app directory. Ensure the
# repository package root is importable in both cases before importing ``app.*`` modules.
REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

import streamlit as st
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from app.chat_backend import get_chatbot, retrieve_all_threads, stream_chat


st.set_page_config(page_title="Kaya Kopi Ops Copilot", page_icon="☕", layout="wide")


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
            except Exception as error:
                yield (
                    "I couldn't complete that check. Confirm the database is available and "
                    f"the LLM configuration is valid. Technical detail: `{type(error).__name__}`."
                )

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
