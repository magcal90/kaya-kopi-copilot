#!/usr/bin/env python3
"""Run manual, non-deterministic acceptance questions through the real copilot."""

from __future__ import annotations

from uuid import uuid4

from langchain_core.messages import AIMessage, HumanMessage

from app.chat_backend import get_chatbot


CASES = [
    (
        "Retrieve sales for legacy outlet code AMK-3A and explain which canonical outlet it belongs to.",
        "Must resolve AMK-3A to AMK-03, return sales, and cite the alias evidence.",
    ),
    (
        "Which outlet has the highest wastage, and can we make that comparison across all twelve outlets?",
        "Must name BDK-01 among measured outlets, include 640.400 kg, and refuse a twelve-outlet ranking.",
    ),
    (
        "Which outlets appear overstaffed in June 2026 based on paid roster hours and authoritative gross takings?",
        "Must not classify any outlet without an approved threshold; must exclude partial-POS outlets from productivity comparison.",
    ),
    (
        "How much did we spend with each supplier by month, and which invoices were excluded or require review?",
        "Must provide supplier-month figures and identify excluded invoice INV-012601-458 as REVIEW_REQUIRED.",
    ),
    (
        "Why does purchase record INV-012508-182 not match the scanned invoice? Is GST responsible for the difference?",
        "Must distinguish identity match from amount mismatch, state the S$9.33 subtotal difference, reject GST as the cause, and leave cause undetermined.",
    ),
    (
        "Which supplier increased its prices the most over the past year? Show evidence from the scanned invoice lines.",
        "Must identify Mewah/SUP-04 condensed milk as the largest comparable percentage increase (15.23%) with first/latest invoice evidence.",
    ),
]


def main() -> None:
    chatbot = get_chatbot()
    for number, (question, expected) in enumerate(CASES, start=1):
        result = chatbot.invoke(
            {"messages": [HumanMessage(content=question)]},
            config={"configurable": {"thread_id": f"acceptance-{uuid4()}"}},
        )
        answers = [message.content for message in result["messages"] if isinstance(message, AIMessage) and message.content]
        answer = answers[-1] if answers else "<NO FINAL ANSWER>"
        print(f"\n=== {number}. QUESTION ===\n{question}")
        print(f"\nEXPECTED CHECK\n{expected}")
        print(f"\nANSWER\n{answer}")


if __name__ == "__main__":
    main()
