#!/usr/bin/env python3
"""Parse PaddleOCR invoice sidecars into invoice and line-item staging data."""

from __future__ import annotations

import argparse
import csv
import json
import re
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

MONEY = re.compile(r"^-?\d+(?:\.\d{1,2})?$")
INVOICE_NUMBER = re.compile(r"INV-\d{6}-\d{3}", re.IGNORECASE)


def project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def parse_args() -> argparse.Namespace:
    root = project_root()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--input-dir",
        type=Path,
        default=root / "runtime" / "ocr" / "supplier_invoices",
        help="directory containing *.ocr.json files",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=root / "runtime" / "structured",
        help="directory for invoices.csv and invoice_items.csv",
    )
    return parser.parse_args()


def normalized(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()


def decimal_value(text: str) -> Decimal | None:
    clean = text.replace(",", "").replace("$", "").strip()
    if not MONEY.fullmatch(clean):
        return None
    try:
        return Decimal(clean)
    except InvalidOperation:
        return None


def decimal_text(value: Decimal | None) -> str:
    return f"{value:.2f}" if value is not None else ""


def value_after_label(lines: list[str], labels: tuple[str, ...]) -> Decimal | None:
    for index, line in enumerate(lines):
        key = normalized(line)
        if key.startswith("gst reg"):
            continue
        if any(key == label or key.startswith(label + " ") for label in labels):
            # Only treat content after a colon as an inline amount. Digits in
            # labels such as ``GST (9%):`` describe the rate, not the value.
            tail = line.split(":", 1)[1].strip() if ":" in line else ""
            if tail:
                inline = re.findall(r"\d+(?:\.\d{1,2})?", tail)
                if inline:
                    return decimal_value(inline[-1])
            if index + 1 < len(lines):
                return decimal_value(lines[index + 1])
    return None


def field_value(lines: list[str], label: str) -> str:
    for line in lines:
        if normalized(line).startswith(label):
            return line.split(":", 1)[1].strip() if ":" in line else ""
    return ""


def parse_date(raw: str) -> str:
    for pattern in ("%d/%m/%Y", "%d-%m-%Y"):
        try:
            return datetime.strptime(raw, pattern).date().isoformat()
        except ValueError:
            pass
    return raw


def center_x(region: dict[str, Any]) -> float:
    box = region["bbox"]
    return float(box["left"]) + float(box["width"]) / 2


def table_items(regions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    headers: dict[str, dict[str, Any]] = {}
    subtotal_top: int | None = None
    for region in regions:
        key = normalized(region["text"])
        if key in {"item description", "iterm description"}:
            headers["description"] = region
        elif key == "qty":
            headers["quantity"] = region
        elif key == "unit price":
            headers["unit_price"] = region
        elif key == "amount":
            headers["amount"] = region
        elif key == "subtotal":
            subtotal_top = int(region["bbox"]["top"])

    if len(headers) < 4 or subtotal_top is None:
        return []

    table_top = max(int(header["bbox"]["top"]) for header in headers.values())
    column_centers = {
        key: center_x(headers[key]) for key in ("quantity", "unit_price", "amount")
    }
    descriptions: list[dict[str, Any]] = []
    numeric_columns: dict[str, list[dict[str, Any]]] = {
        "quantity": [],
        "unit_price": [],
        "amount": [],
    }
    description_boundary = (
        center_x(headers["description"]) + column_centers["quantity"]
    ) / 2

    for region in regions:
        top = int(region["bbox"]["top"])
        text = region["text"].strip()
        # The subtotal value can sit a few pixels above its label because OCR
        # boxes have different heights. Leave a small gutter below item rows.
        if top <= table_top or top >= subtotal_top - 10:
            continue
        key = normalized(text)
        if key in {"item description", "iterm description", "qty", "unit price", "amount"}:
            continue
        x = center_x(region)
        number = decimal_value(text)
        if x < description_boundary and number is None:
            descriptions.append(region)
        elif number is not None:
            column = min(column_centers, key=lambda name: abs(x - column_centers[name]))
            numeric_columns[column].append(region)

    for values in numeric_columns.values():
        values.sort(key=lambda region: int(region["bbox"]["top"]))
    descriptions.sort(key=lambda region: int(region["bbox"]["top"]))
    row_count = max([len(descriptions), *(len(values) for values in numeric_columns.values())])

    items: list[dict[str, Any]] = []
    for index in range(row_count):
        parts = {
            "description": descriptions[index] if index < len(descriptions) else None,
            **{
                name: values[index] if index < len(values) else None
                for name, values in numeric_columns.items()
            },
        }
        quantity = decimal_value(parts["quantity"]["text"]) if parts["quantity"] else None
        unit_price = decimal_value(parts["unit_price"]["text"]) if parts["unit_price"] else None
        amount = decimal_value(parts["amount"]["text"]) if parts["amount"] else None
        confidences = [float(part["confidence"]) for part in parts.values() if part]
        complete = all(parts.values())
        line_total_valid = (
            quantity is not None
            and unit_price is not None
            and amount is not None
            and abs(quantity * unit_price - amount) <= Decimal("0.01")
        )
        notes = []
        if not complete:
            notes.append("missing OCR table field")
        if complete and not line_total_valid:
            notes.append("quantity x unit price does not equal amount")
        items.append(
            {
                "line_number": index + 1,
                "description": parts["description"]["text"] if parts["description"] else "",
                "quantity": decimal_text(quantity),
                "unit_price": decimal_text(unit_price),
                "amount": decimal_text(amount),
                "mean_field_confidence": (
                    f"{sum(confidences) / len(confidences):.2f}" if confidences else ""
                ),
                "line_total_valid": str(line_total_valid).lower(),
                "extraction_status": "OK" if complete and line_total_valid else "REVIEW_REQUIRED",
                "review_notes": "; ".join(notes),
            }
        )
    return items


def parse_invoice(path: Path) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    lines = [line.strip() for line in payload.get("text", "").splitlines() if line.strip()]
    regions = payload.get("words", [])
    source_file = payload.get("source", path.name.removesuffix(".ocr.json"))
    invoice_match = INVOICE_NUMBER.search("\n".join(lines)) or INVOICE_NUMBER.search(source_file)
    invoice_number = invoice_match.group(0).upper() if invoice_match else ""

    supplier = next(
        (
            line
            for line in lines[:5]
            if "TAX INVOICE" not in line.upper()
            and not normalized(line).startswith(("invoice no", "date", "gst reg no", "blk", "bik"))
        ),
        "",
    )
    supplier_address = next(
        (line for line in lines[:8] if normalized(line).startswith(("blk ", "bik "))), ""
    )
    gst_number = field_value(lines, "gst reg no")
    invoice_date = parse_date(field_value(lines, "date"))
    bill_to = field_value(lines, "bill to")
    subtotal = value_after_label(lines, ("subtotal",))
    gst_amount = value_after_label(lines, ("gst 9", "gst"))
    total = value_after_label(lines, ("total",))
    gst_rate_match = re.search(r"GST\s*\(?\s*(\d+(?:\.\d+)?)\s*%", "\n".join(lines), re.I)
    gst_rate = Decimal(gst_rate_match.group(1)) if gst_rate_match else None
    items = table_items(regions)
    item_sum = sum((decimal_value(item["amount"]) or Decimal(0) for item in items), Decimal(0))
    arithmetic_valid = (
        subtotal is not None
        and gst_amount is not None
        and total is not None
        and abs(subtotal + gst_amount - total) <= Decimal("0.01")
        and abs(item_sum - subtotal) <= Decimal("0.01")
    )
    review_notes = []
    required = {
        "invoice number": invoice_number,
        "supplier": supplier,
        "invoice date": invoice_date,
        "subtotal": subtotal,
        "GST": gst_amount,
        "total": total,
    }
    missing = [name for name, value in required.items() if value in (None, "")]
    if missing:
        review_notes.append("missing " + ", ".join(missing))
    if not arithmetic_valid:
        review_notes.append("invoice arithmetic or item sum mismatch")
    if any(item["extraction_status"] != "OK" for item in items):
        review_notes.append("one or more line items require review")
    if not items:
        review_notes.append("no line items extracted")

    invoice = {
        "source_file": source_file,
        "invoice_number": invoice_number,
        "ocr_engine": payload.get("engine", ""),
        "ocr_language": payload.get("language", ""),
        "ocr_processed_at": payload.get("processed_at", ""),
        "image_width": payload.get("image", {}).get("width", ""),
        "image_height": payload.get("image", {}).get("height", ""),
        "supplier_name": supplier,
        "supplier_address": supplier_address,
        "gst_registration_number": gst_number,
        "invoice_date": invoice_date,
        "bill_to": bill_to,
        "subtotal": decimal_text(subtotal),
        "gst_rate_percent": decimal_text(gst_rate),
        "gst_amount": decimal_text(gst_amount),
        "total": decimal_text(total),
        "payment_terms": field_value(lines, "payment terms"),
        "received_condition": field_value(lines, "received in good condition"),
        "mean_ocr_confidence": payload.get("mean_word_confidence", ""),
        "line_item_count": len(items),
        "arithmetic_valid": str(arithmetic_valid).lower(),
        "extraction_status": "OK" if not review_notes else "REVIEW_REQUIRED",
        "review_notes": "; ".join(review_notes),
        "ocr_json": path.relative_to(project_root()).as_posix(),
    }
    for item in items:
        item["source_file"] = source_file
        item["invoice_number"] = invoice_number
    return invoice, items


def write_csv(path: Path, rows: list[dict[str, Any]], fields: list[str]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def main() -> int:
    args = parse_args()
    input_dir = args.input_dir.expanduser().resolve()
    output_dir = args.output_dir.expanduser().resolve()
    paths = sorted(input_dir.glob("*.ocr.json"))
    if not paths:
        raise SystemExit(f"error: no .ocr.json files found in {input_dir}")

    invoices: list[dict[str, Any]] = []
    items: list[dict[str, Any]] = []
    for path in paths:
        invoice, invoice_items = parse_invoice(path)
        invoices.append(invoice)
        items.extend(invoice_items)

    output_dir.mkdir(parents=True, exist_ok=True)
    invoice_fields = list(invoices[0])
    item_fields = [
        "source_file", "invoice_number", "line_number", "description", "quantity",
        "unit_price", "amount", "mean_field_confidence", "line_total_valid",
        "extraction_status", "review_notes",
    ]
    write_csv(output_dir / "invoices.csv", invoices, invoice_fields)
    write_csv(output_dir / "invoice_items.csv", items, item_fields)
    review_count = sum(row["extraction_status"] != "OK" for row in invoices)
    print(f"Invoices: {len(invoices)} ({review_count} review required)")
    print(f"Invoice items: {len(items)}")
    print(f"Wrote: {output_dir / 'invoices.csv'}")
    print(f"Wrote: {output_dir / 'invoice_items.csv'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
