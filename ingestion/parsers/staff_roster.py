#!/usr/bin/env python3
"""Normalize the client-supplied monthly XLSX roster into assignment and shift rows."""

from __future__ import annotations

import argparse
import csv
import hashlib
import re
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any


DAYS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")
SHIFT_HOURS = {"AM": Decimal("7"), "PM": Decimal("7"), "AM/PM": Decimal("13"), "OFF": Decimal("0")}
REQUIRED_HEADERS = ("Outlet", "Staff Name", "Role", *DAYS, "Hourly Rate")


@dataclass(frozen=True)
class ParsedRoster:
    roster_month: str
    source_file: str
    source_version_key: str
    content_sha256: str
    assignments: list[dict[str, str]]
    shifts: list[dict[str, str]]
    issues: list[dict[str, str]]


def project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def stable_id(prefix: str, *parts: str) -> str:
    digest = hashlib.sha256("\x1f".join(parts).encode("utf-8")).hexdigest()[:16]
    return f"{prefix}_{digest}"


def _roster_month(title: str, path: Path) -> str:
    match = re.search(r"\b(JANUARY|FEBRUARY|MARCH|APRIL|MAY|JUNE|JULY|AUGUST|SEPTEMBER|OCTOBER|NOVEMBER|DECEMBER)\s+(20\d{2})\b", title.upper())
    if match:
        return datetime.strptime(f"{match.group(1)} {match.group(2)}", "%B %Y").strftime("%Y-%m")
    filename_match = re.search(r"([a-z]{3})(20\d{2})", path.stem.lower())
    if filename_match:
        return datetime.strptime("".join(filename_match.groups()), "%b%Y").strftime("%Y-%m")
    raise ValueError(f"cannot determine roster month from workbook title or filename: {path.name}")


def _normalise_rate(raw_value: Any) -> tuple[str, str, str]:
    raw = str(raw_value).strip() if raw_value is not None else ""
    if raw.upper() == "TBC":
        return raw, "13.00", "CLIENT_APPROVED_DEFAULT"
    cleaned = raw.replace("$", "").replace("/hr", "").strip()
    try:
        value = Decimal(cleaned)
    except InvalidOperation as error:
        raise ValueError(f"unsupported hourly rate: {raw!r}") from error
    if value < 0:
        raise ValueError(f"hourly rate cannot be negative: {raw!r}")
    return raw, f"{value:.2f}", "CONFIRMED"


def parse_roster(path: Path) -> ParsedRoster:
    """Parse one roster workbook through its public file boundary."""
    try:
        from openpyxl import load_workbook
    except ModuleNotFoundError as error:
        raise RuntimeError("openpyxl is required to parse staff roster XLSX files") from error

    path = path.resolve()
    raw_bytes = path.read_bytes()
    content_sha256 = hashlib.sha256(raw_bytes).hexdigest()
    source_file = f"tabular/{path.name}"
    source_version_key = hashlib.sha256(f"{source_file}\x1f{content_sha256}".encode()).hexdigest()
    workbook = load_workbook(path, read_only=True, data_only=True)
    if len(workbook.worksheets) != 1:
        raise ValueError(f"expected one roster worksheet, found {len(workbook.worksheets)}")
    worksheet = workbook.worksheets[0]
    rows = list(worksheet.iter_rows(values_only=True))
    if not rows:
        raise ValueError("roster workbook is empty")

    header_index = next(
        (index for index, row in enumerate(rows) if tuple(str(value).strip() for value in row if value is not None) == REQUIRED_HEADERS),
        None,
    )
    if header_index is None:
        raise ValueError(f"unsupported roster schema in worksheet {worksheet.title!r}")
    title = " ".join(str(value) for row in rows[:header_index] for value in row if value)
    roster_month = _roster_month(title, path)

    assignments: list[dict[str, str]] = []
    shifts: list[dict[str, str]] = []
    issues: list[dict[str, str]] = []
    for source_row_number, values in enumerate(rows[header_index + 1 :], start=header_index + 2):
        if not any(value is not None and str(value).strip() for value in values):
            continue
        row = dict(zip(REQUIRED_HEADERS, values, strict=False))
        outlet_code = str(row.get("Outlet") or "").strip().upper()
        staff_name = str(row.get("Staff Name") or "").strip()
        role = str(row.get("Role") or "").strip()
        locator = f"sheet={worksheet.title};row={source_row_number}"
        assignment_id = stable_id("assign", source_version_key, str(source_row_number), outlet_code)
        staff_key = stable_id("staff", staff_name.casefold())
        try:
            raw_rate, hourly_rate, rate_status = _normalise_rate(row.get("Hourly Rate"))
        except ValueError as error:
            raw_rate = str(row.get("Hourly Rate") or "").strip()
            hourly_rate = ""
            rate_status = "REVIEW_REQUIRED"
            issues.append(
                {
                    "issue_id": stable_id("dq", assignment_id, "hourly_rate"),
                    "source_file": source_file,
                    "source_locator": locator,
                    "record_key": assignment_id,
                    "rule_code": "INVALID_HOURLY_RATE",
                    "severity": "ERROR",
                    "details": str(error),
                    "resolution_status": "OPEN",
                }
            )
        assignments.append(
            {
                "assignment_id": assignment_id,
                "staff_key": staff_key,
                "staff_name": staff_name,
                "outlet_code": outlet_code,
                "role": role,
                "raw_hourly_rate": raw_rate,
                "hourly_rate_sgd": hourly_rate,
                "rate_status": rate_status,
                "source_file": source_file,
                "source_version_key": source_version_key,
                "content_sha256": content_sha256,
                "source_row_number": str(source_row_number),
                "source_locator": locator,
                "roster_month": roster_month,
            }
        )
        for day in DAYS:
            raw_shift = str(row.get(day) or "").strip().upper()
            hours = SHIFT_HOURS.get(raw_shift)
            shift_id = stable_id("shift", assignment_id, day)
            if hours is None:
                issues.append(
                    {
                        "issue_id": stable_id("dq", shift_id, "shift_code"),
                        "source_file": source_file,
                        "source_locator": locator,
                        "record_key": shift_id,
                        "rule_code": "UNKNOWN_SHIFT_CODE",
                        "severity": "ERROR",
                        "details": f"unsupported {day} shift code: {raw_shift!r}",
                        "resolution_status": "OPEN",
                    }
                )
            shifts.append(
                {
                    "shift_id": shift_id,
                    "assignment_id": assignment_id,
                    "day_of_week": day.upper(),
                    "raw_shift_code": raw_shift,
                    "paid_hours": f"{hours:.2f}" if hours is not None else "",
                    "validation_status": "OK" if hours is not None else "REVIEW_REQUIRED",
                }
            )

    return ParsedRoster(roster_month, source_file, source_version_key, content_sha256, assignments, shifts, issues)


def _write_csv(path: Path, rows: list[dict[str, str]], fields: list[str]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    root = project_root()
    parser.add_argument("--input", type=Path, default=root / "data" / "tabular" / "staff_roster_jun2026.xlsx")
    parser.add_argument("--output-dir", type=Path, default=root / "runtime" / "structured")
    args = parser.parse_args()
    parsed = parse_roster(args.input)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    _write_csv(args.output_dir / "staff_roster_assignments.csv", parsed.assignments, list(parsed.assignments[0]))
    _write_csv(args.output_dir / "staff_roster_shifts.csv", parsed.shifts, list(parsed.shifts[0]))
    issue_fields = ["issue_id", "source_file", "source_locator", "record_key", "rule_code", "severity", "details", "resolution_status"]
    _write_csv(args.output_dir / "staff_roster_quality_issues.csv", parsed.issues, issue_fields)
    print(f"Roster month: {parsed.roster_month}")
    print(f"Assignments: {len(parsed.assignments)}")
    print(f"Shift patterns: {len(parsed.shifts)}")
    print(f"Quality issues: {len(parsed.issues)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
