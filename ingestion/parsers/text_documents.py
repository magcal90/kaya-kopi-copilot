#!/usr/bin/env python3
"""Parse WhatsApp and email exports into structured, retrieval-ready staging data."""

from __future__ import annotations

import argparse
import csv
import hashlib
import re
from datetime import datetime
from email import policy
from email.parser import Parser
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

WHATSAPP_LINE = re.compile(
    r"^(?P<date>\d{2}/\d{2}/\d{2}), (?P<time>\d{2}:\d{2}) - "
    r"(?P<sender>[^:]+): (?P<message>.*)$"
)
SENDER_GROUP = re.compile(r"^(?P<name>.*?)\s*\((?P<group>[^()]+)\)$")
OUTLET_CODE = re.compile(r"\b[A-Z]{3}-(?:\d{2}|[0-9][A-Z])\b")
SUPPLIER_ALIASES = {
    "Ban Seng": "BAN SENG EGGS & PROVISIONS",
    "Mewah": "MEWAH SUGAR TRADING",
    "Heng Huat": "HENG HUAT COFFEE ROASTERS",
    "Sunrise": "SUNRISE BAKERY SUPPLIES",
    "D'Best": "D'BEST FROZEN FOODS",
}
SINGAPORE = ZoneInfo("Asia/Singapore")


def project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def parse_args() -> argparse.Namespace:
    root = project_root()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--docs-dir",
        type=Path,
        default=root / "data" / "docs",
        help="root containing whatsapp_exports and emails",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=root / "runtime" / "structured",
        help="directory for generated CSV files",
    )
    return parser.parse_args()


def stable_id(prefix: str, *parts: str) -> str:
    value = "\x1f".join(parts).encode("utf-8")
    return f"{prefix}_{hashlib.sha256(value).hexdigest()[:16]}"


def mentions(text: str) -> tuple[str, str]:
    outlets = sorted(set(OUTLET_CODE.findall(text.upper())))
    lowered = text.casefold()
    suppliers = sorted(
        canonical
        for alias, canonical in SUPPLIER_ALIASES.items()
        if alias.casefold() in lowered
    )
    return "|".join(outlets), "|".join(suppliers)


def parse_whatsapp(path: Path, docs_dir: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    lines = path.read_text(encoding="utf-8-sig").splitlines()
    title = lines[0].strip() if lines else ""
    source_file = path.relative_to(docs_dir).as_posix()
    messages: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None

    for line_number, line in enumerate(lines[1:], start=2):
        match = WHATSAPP_LINE.match(line)
        if match:
            if current:
                messages.append(current)
            sender_display = match.group("sender").strip()
            sender_match = SENDER_GROUP.match(sender_display)
            occurred_at = datetime.strptime(
                f"{match.group('date')} {match.group('time')}", "%d/%m/%y %H:%M"
            ).replace(tzinfo=SINGAPORE)
            current = {
                "source_file": source_file,
                "chat_title": title,
                "sent_at": occurred_at.isoformat(),
                "sender_display_name": sender_display,
                "sender_name": (
                    sender_match.group("name").strip() if sender_match else sender_display
                ),
                "sender_group": sender_match.group("group").strip() if sender_match else "",
                "message_text": match.group("message").strip(),
                "source_line_start": line_number,
                "source_line_end": line_number,
                "parse_status": "OK",
            }
        elif current and line.strip():
            current["message_text"] += "\n" + line
            current["source_line_end"] = line_number
    if current:
        messages.append(current)

    chunks: list[dict[str, Any]] = []
    for message in messages:
        locator = (
            f"lines={message['source_line_start']}-{message['source_line_end']}"
        )
        message_id = stable_id(
            "wa",
            source_file,
            locator,
            message["sender_display_name"],
            message["message_text"],
        )
        outlet_codes, suppliers = mentions(message["message_text"])
        message.update(
            {
                "message_id": message_id,
                "mentioned_outlet_codes": outlet_codes,
                "mentioned_suppliers": suppliers,
                "source_locator": locator,
            }
        )
        chunks.append(
            {
                "chunk_id": message_id,
                "source_type": "whatsapp_message",
                "source_file": source_file,
                "occurred_at": message["sent_at"],
                "author": message["sender_display_name"],
                "title": title,
                "chunk_text": message["message_text"],
                "source_locator": locator,
                "mentioned_outlet_codes": outlet_codes,
                "mentioned_suppliers": suppliers,
            }
        )
    return messages, chunks


def parse_email(path: Path, docs_dir: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    raw = path.read_text(encoding="utf-8-sig")
    lines = raw.splitlines()
    message = Parser(policy=policy.default).parsestr(raw)
    body = message.get_body(preferencelist=("plain",))
    body_text = (body.get_content() if body else message.get_payload()).strip()
    source_file = path.relative_to(docs_dir).as_posix()
    date_header = str(message.get("Date", ""))
    try:
        occurred_at = parsedate_to_datetime(date_header).isoformat()
    except (TypeError, ValueError):
        occurred_at = ""
    body_start = next((index + 2 for index, line in enumerate(lines) if not line.strip()), 1)
    locator = f"lines={body_start}-{len(lines)}"
    email_id = stable_id(
        "email", source_file, str(message.get("From", "")), str(message.get("Subject", ""))
    )
    outlet_codes, suppliers = mentions(raw)
    row = {
        "email_id": email_id,
        "source_file": source_file,
        "from_address": str(message.get("From", "")),
        "to_address": str(message.get("To", "")),
        "sent_at": occurred_at,
        "subject": str(message.get("Subject", "")),
        "body_text": body_text,
        "mentioned_outlet_codes": outlet_codes,
        "mentioned_suppliers": suppliers,
        "source_locator": locator,
        "parse_status": "OK" if occurred_at and body_text else "REVIEW_REQUIRED",
    }
    chunk_text = (
        f"Subject: {row['subject']}\nFrom: {row['from_address']}\n"
        f"Date: {row['sent_at']}\n\n{body_text}"
    )
    chunk = {
        "chunk_id": email_id,
        "source_type": "email",
        "source_file": source_file,
        "occurred_at": occurred_at,
        "author": row["from_address"],
        "title": row["subject"],
        "chunk_text": chunk_text,
        "source_locator": locator,
        "mentioned_outlet_codes": outlet_codes,
        "mentioned_suppliers": suppliers,
    }
    return row, chunk


def write_csv(path: Path, rows: list[dict[str, Any]], fields: list[str]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def main() -> int:
    args = parse_args()
    docs_dir = args.docs_dir.expanduser().resolve()
    output_dir = args.output_dir.expanduser().resolve()
    whatsapp_paths = sorted((docs_dir / "whatsapp_exports").glob("*.txt"))
    email_paths = sorted((docs_dir / "emails").glob("*.txt"))
    if not whatsapp_paths and not email_paths:
        raise SystemExit(f"error: no supported text documents found under {docs_dir}")

    whatsapp_rows: list[dict[str, Any]] = []
    email_rows: list[dict[str, Any]] = []
    chunks: list[dict[str, Any]] = []
    for path in whatsapp_paths:
        messages, message_chunks = parse_whatsapp(path, docs_dir)
        whatsapp_rows.extend(messages)
        chunks.extend(message_chunks)
    for path in email_paths:
        email_row, email_chunk = parse_email(path, docs_dir)
        email_rows.append(email_row)
        chunks.append(email_chunk)

    output_dir.mkdir(parents=True, exist_ok=True)
    whatsapp_fields = [
        "message_id", "source_file", "chat_title", "sent_at", "sender_display_name",
        "sender_name", "sender_group", "message_text", "mentioned_outlet_codes",
        "mentioned_suppliers", "source_locator", "source_line_start", "source_line_end",
        "parse_status",
    ]
    email_fields = [
        "email_id", "source_file", "from_address", "to_address", "sent_at", "subject",
        "body_text", "mentioned_outlet_codes", "mentioned_suppliers", "source_locator",
        "parse_status",
    ]
    chunk_fields = [
        "chunk_id", "source_type", "source_file", "occurred_at", "author", "title",
        "chunk_text", "source_locator", "mentioned_outlet_codes", "mentioned_suppliers",
    ]
    write_csv(output_dir / "whatsapp_messages.csv", whatsapp_rows, whatsapp_fields)
    write_csv(output_dir / "emails.csv", email_rows, email_fields)
    write_csv(output_dir / "document_chunks.csv", chunks, chunk_fields)
    print(f"WhatsApp messages: {len(whatsapp_rows)}")
    print(f"Emails: {len(email_rows)}")
    print(f"Retrieval chunks: {len(chunks)}")
    print(f"Wrote structured files to: {output_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
