#!/usr/bin/env python3
"""Normalize heterogeneous outlet CSVs into loss-aware staging data."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

SCHEMAS = {
    ("Date", "Total Sales (SGD)", "No of Cups", "Remarks"): {
        "date": "Date", "date_format": "%d/%m/%Y", "sales": "Total Sales (SGD)",
        "volume": "No of Cups", "volume_measure": "receipts", "remarks": "Remarks",
    },
    ("date", "sales$", "txns"): {
        "date": "date", "date_format": "%Y-%m-%d", "sales": "sales$",
        "volume": "txns", "volume_measure": "receipts",
    },
    ("DAY", "REVENUE", "CUPS", "WASTAGE_KG"): {
        "date": "DAY", "date_format": "%d-%b-%y", "sales": "REVENUE",
        "volume": "CUPS", "volume_measure": "receipts", "wastage": "WASTAGE_KG",
    },
    ("Business Date", "Gross Takings", "Customer Count", "Weather"): {
        "date": "Business Date", "date_format": "%m/%d/%Y", "sales": "Gross Takings",
        "volume": "Customer Count", "volume_measure": "receipts", "weather": "Weather",
    },
}


def project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def parse_args() -> argparse.Namespace:
    root = project_root()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--input-dir", type=Path, default=root / "data" / "tabular",
        help="directory containing daily_summary_*.csv files",
    )
    parser.add_argument(
        "--output-dir", type=Path, default=root / "runtime" / "structured",
        help="directory for normalized and quality-issue CSV files",
    )
    return parser.parse_args()


def stable_id(prefix: str, *parts: str) -> str:
    digest = hashlib.sha256("\x1f".join(parts).encode("utf-8")).hexdigest()[:16]
    return f"{prefix}_{digest}"


def outlet_from_filename(path: Path) -> str:
    prefix = "daily_summary_"
    if not path.stem.startswith(prefix):
        raise ValueError(f"unexpected filename: {path.name}")
    return path.stem.removeprefix(prefix)


def parse_decimal(raw: str) -> Decimal:
    clean = raw.strip().replace("S$", "").replace("$", "").replace(",", "")
    return Decimal(clean)


def decimal_text(value: Decimal | None, places: int) -> str:
    return f"{value:.{places}f}" if value is not None else ""


def source_version_key(source_file: str, content_sha256: str) -> str:
    return hashlib.sha256(f"{source_file}\x1f{content_sha256}".encode()).hexdigest()


def normalize_file(path: Path, input_dir: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    raw_bytes = path.read_bytes()
    content_sha256 = hashlib.sha256(raw_bytes).hexdigest()
    source_file = path.relative_to(input_dir.parent).as_posix()
    version_key = source_version_key(source_file, content_sha256)
    outlet_code = outlet_from_filename(path)
    records: list[dict[str, Any]] = []
    issues: list[dict[str, Any]] = []

    with path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        headers = tuple(reader.fieldnames or ())
        schema = SCHEMAS.get(headers)
        if schema is None:
            raise ValueError(f"unsupported CSV schema in {path.name}: {headers}")

        for row_number, raw in enumerate(reader, start=2):
            notes: list[str] = []
            raw_date = (raw.get(schema["date"]) or "").strip()
            raw_sales = (raw.get(schema["sales"]) or "").strip()
            raw_volume = (raw.get(schema["volume"]) or "").strip()
            raw_wastage = (raw.get(schema.get("wastage", "")) or "").strip()
            try:
                business_date = datetime.strptime(raw_date, schema["date_format"]).date()
            except ValueError:
                business_date = None
                notes.append("invalid business date")
            try:
                sales = parse_decimal(raw_sales)
                if sales < 0:
                    notes.append("negative sales")
            except InvalidOperation:
                sales = None
                notes.append("invalid sales amount")
            try:
                volume = int(raw_volume)
                if volume < 0:
                    notes.append("negative reported volume")
            except ValueError:
                volume = None
                notes.append("invalid reported volume")
            try:
                wastage = parse_decimal(raw_wastage) if raw_wastage else None
                if wastage is not None and wastage < 0:
                    notes.append("negative wastage")
            except InvalidOperation:
                wastage = None
                notes.append("invalid wastage amount")

            locator = f"row={row_number}"
            record_id = stable_id("daily", version_key, locator)
            record = {
                "record_id": record_id,
                "source_file": source_file,
                "source_version_key": version_key,
                "content_sha256": content_sha256,
                "source_row_number": row_number,
                "source_locator": locator,
                "outlet_code_raw": outlet_code,
                "outlet_code_canonical": outlet_code,
                "raw_business_date": raw_date,
                "business_date": business_date.isoformat() if business_date else "",
                "raw_sales_amount": raw_sales,
                "sales_amount_sgd": decimal_text(sales, 2),
                "source_sales_label": schema["sales"],
                "gross_takings_sgd": decimal_text(sales, 2),
                "raw_reported_volume": raw_volume,
                "source_volume_label": schema["volume"],
                "reported_volume": volume if volume is not None else "",
                "volume_measure": schema["volume_measure"],
                "raw_wastage_kg": raw_wastage,
                "wastage_kg": decimal_text(wastage, 3),
                "remarks": (raw.get(schema.get("remarks", "")) or "").strip(),
                "weather": (raw.get(schema.get("weather", "")) or "").strip(),
                "validation_status": "OK" if not notes else "REVIEW_REQUIRED",
                "validation_notes": "; ".join(notes),
            }
            records.append(record)
            for note in notes:
                issues.append(
                    {
                        "issue_id": stable_id("dq", record_id, note),
                        "source_file": source_file,
                        "outlet_code": outlet_code,
                        "business_date": record["business_date"],
                        "source_locator": locator,
                        "rule_code": note.upper().replace(" ", "_"),
                        "severity": "ERROR",
                        "details": note,
                        "resolution_status": "OPEN",
                    }
                )
    return records, issues


def coverage_issues(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    valid_dates = [date.fromisoformat(row["business_date"]) for row in records if row["business_date"]]
    if not valid_dates:
        return []
    period_start, period_end = min(valid_dates), max(valid_dates)
    expected = {
        period_start + timedelta(days=offset)
        for offset in range((period_end - period_start).days + 1)
    }
    by_outlet: dict[str, set[date]] = {}
    source_by_outlet: dict[str, str] = {}
    for row in records:
        outlet = row["outlet_code_canonical"]
        source_by_outlet[outlet] = row["source_file"]
        if row["business_date"]:
            by_outlet.setdefault(outlet, set()).add(date.fromisoformat(row["business_date"]))

    issues: list[dict[str, Any]] = []
    for outlet, present in sorted(by_outlet.items()):
        for missing in sorted(expected - present):
            details = (
                f"No daily summary row for {outlet} on {missing.isoformat()}; "
                "this may represent closure or missing data and requires confirmation."
            )
            issues.append(
                {
                    "issue_id": stable_id("dq", source_by_outlet[outlet], missing.isoformat()),
                    "source_file": source_by_outlet[outlet],
                    "outlet_code": outlet,
                    "business_date": missing.isoformat(),
                    "source_locator": "",
                    "rule_code": "MISSING_DAILY_SUMMARY",
                    "severity": "WARNING",
                    "details": details,
                    "resolution_status": "OPEN",
                }
            )
    return issues


def write_csv(path: Path, rows: list[dict[str, Any]], fields: list[str]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def main() -> int:
    args = parse_args()
    input_dir = args.input_dir.expanduser().resolve()
    output_dir = args.output_dir.expanduser().resolve()
    paths = sorted(input_dir.glob("daily_summary_*.csv"))
    if not paths:
        raise SystemExit(f"error: no daily-summary CSV files found in {input_dir}")

    records: list[dict[str, Any]] = []
    issues: list[dict[str, Any]] = []
    for path in paths:
        file_records, file_issues = normalize_file(path, input_dir)
        records.extend(file_records)
        issues.extend(file_issues)
    issues.extend(coverage_issues(records))

    output_dir.mkdir(parents=True, exist_ok=True)
    record_fields = list(records[0])
    issue_fields = [
        "issue_id", "source_file", "outlet_code", "business_date", "source_locator",
        "rule_code", "severity", "details", "resolution_status",
    ]
    write_csv(output_dir / "daily_outlet_summaries.csv", records, record_fields)
    write_csv(output_dir / "tabular_quality_issues.csv", issues, issue_fields)
    print(f"Source files: {len(paths)}")
    print(f"Daily summary rows: {len(records)}")
    print(f"Quality issues: {len(issues)}")
    print(f"Wrote structured files to: {output_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
