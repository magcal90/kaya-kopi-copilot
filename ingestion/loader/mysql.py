#!/usr/bin/env python3
"""Idempotently load parsed staging datasets through the MySQL adapter."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, Iterable


def project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default=os.getenv("KAYA_DB_HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(os.getenv("KAYA_DB_PORT", "3306")))
    parser.add_argument("--user", default=os.getenv("KAYA_DB_USER", "root"))
    parser.add_argument("--password", default=os.getenv("KAYA_DB_PASSWORD", ""))
    parser.add_argument("--database", default=os.getenv("KAYA_DB_NAME", "kayakopi"))
    parser.add_argument("--project-root", type=Path, default=project_root())
    return parser.parse_args()


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def version_key(source_uri: str, content_sha256: str) -> str:
    return hashlib.sha256(f"{source_uri}\x1f{content_sha256}".encode()).hexdigest()


def stable_key(prefix: str, *parts: str) -> str:
    digest = hashlib.sha256("\x1f".join(parts).encode()).hexdigest()[:16]
    return f"{prefix}_{digest}"


def nullable(value: str | None) -> str | None:
    value = (value or "").strip()
    return value or None


def bool_value(value: str) -> bool:
    return value.strip().lower() in {"1", "true", "yes"}


def local_datetime(value: str) -> datetime | None:
    if not value:
        return None
    parsed = datetime.fromisoformat(value)
    return parsed.replace(tzinfo=None)


def batches(values: list[tuple[Any, ...]], size: int = 500) -> Iterable[list[tuple[Any, ...]]]:
    for start in range(0, len(values), size):
        yield values[start : start + size]


class Loader:
    def __init__(self, connection: Any, root: Path) -> None:
        self.connection = connection
        self.root = root
        self.structured = root / "runtime" / "structured"
        self.source_ids: dict[str, int] = {}
        self.outlet_ids: dict[str, int] = {}
        self.invoice_ids: dict[str, int] = {}
        self.staff_assignment_ids: dict[str, int] = {}
        self.supplier_codes_by_name: dict[str, str] = {}

    def execute_many(self, sql: str, values: list[tuple[Any, ...]]) -> None:
        with self.connection.cursor() as cursor:
            for group in batches(values):
                cursor.executemany(sql, group)

    def load_outlets(self) -> None:
        with self.connection.cursor() as cursor:
            cursor.execute("SELECT outlet_id, outlet_code FROM outlets")
            self.outlet_ids = {row["outlet_code"]: row["outlet_id"] for row in cursor.fetchall()}
        if not self.outlet_ids:
            raise RuntimeError("legacy outlets table is empty; import data/sql/kayakopi_pos.sql first")

    def load_suppliers(self) -> None:
        with self.connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT supplier_code, MIN(supplier_name) AS supplier_name,
                       COUNT(DISTINCT UPPER(supplier_name)) AS name_count
                FROM supplier_purchases
                GROUP BY supplier_code
                """
            )
            suppliers = list(cursor.fetchall())
            if any(row["name_count"] != 1 for row in suppliers):
                raise RuntimeError("supplier code maps to multiple legacy supplier names")
            for row in suppliers:
                cursor.execute(
                    """
                    INSERT INTO supplier
                        (supplier_code, canonical_name, validation_status)
                    VALUES (%s,%s,'VERIFIED')
                    ON DUPLICATE KEY UPDATE
                        canonical_name=VALUES(canonical_name),
                        validation_status=VALUES(validation_status)
                    """,
                    (row["supplier_code"], row["supplier_name"]),
                )
                self.supplier_codes_by_name[row["supplier_name"].strip().upper()] = row[
                    "supplier_code"
                ]

    def upsert_source(
        self,
        source_key: str,
        path: Path,
        document_type: str,
        mime_type: str,
        *,
        raw_text: str | None = None,
        ocr_json_uri: str | None = None,
        confidence: str | None = None,
        status: str = "OK",
        supplied_version_key: str | None = None,
    ) -> int:
        content_hash = sha256_file(path)
        source_uri = path.relative_to(self.root).as_posix()
        source_version = supplied_version_key or version_key(source_uri, content_hash)
        sql = """
            INSERT INTO source_document
                (source_version_key, source_uri, content_sha256, document_type, mime_type,
                 raw_text, ocr_json_uri, mean_ocr_confidence, extraction_status)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
            ON DUPLICATE KEY UPDATE
                source_document_id=LAST_INSERT_ID(source_document_id),
                source_uri=VALUES(source_uri), content_sha256=VALUES(content_sha256),
                document_type=VALUES(document_type), mime_type=VALUES(mime_type),
                raw_text=VALUES(raw_text), ocr_json_uri=VALUES(ocr_json_uri),
                mean_ocr_confidence=VALUES(mean_ocr_confidence),
                extraction_status=VALUES(extraction_status)
        """
        with self.connection.cursor() as cursor:
            cursor.execute(
                sql,
                (
                    source_version, source_uri, content_hash, document_type, mime_type,
                    raw_text, ocr_json_uri, nullable(confidence), status,
                ),
            )
            source_id = int(cursor.lastrowid)
        self.source_ids[source_key] = source_id
        return source_id

    def load_source_documents(
        self,
        daily_rows: list[dict[str, str]],
        invoice_rows: list[dict[str, str]],
        chunk_rows: list[dict[str, str]],
        roster_rows: list[dict[str, str]],
    ) -> None:
        daily_by_file = {row["source_file"]: row for row in daily_rows}
        for source_file, sample in sorted(daily_by_file.items()):
            self.upsert_source(
                source_file,
                self.root / "data" / source_file,
                "daily_outlet_summary",
                "text/csv",
                supplied_version_key=sample["source_version_key"],
            )

        for row in invoice_rows:
            if row["supplier_name"].strip().upper() not in self.supplier_codes_by_name:
                raise RuntimeError(
                    f"invoice supplier has no canonical supplier code: {row['supplier_name']}"
                )
            source_file = row["source_file"]
            image_path = self.root / "data" / "images" / source_file
            json_path = self.root / row["ocr_json"]
            payload = json.loads(json_path.read_text(encoding="utf-8"))
            self.upsert_source(
                source_file,
                image_path,
                "supplier_invoice",
                "image/jpeg",
                raw_text=payload.get("text", ""),
                ocr_json_uri=row["ocr_json"],
                confidence=row["mean_ocr_confidence"],
                status=row["extraction_status"],
            )

        for source_file in sorted({row["source_file"] for row in chunk_rows}):
            source_path = self.root / "data" / "docs" / source_file
            document_type = "email" if source_file.startswith("emails/") else "whatsapp_export"
            self.upsert_source(
                source_file,
                source_path,
                document_type,
                "text/plain",
                raw_text=source_path.read_text(encoding="utf-8-sig"),
            )

        for source_file in sorted({row["source_file"] for row in roster_rows}):
            sample = next(row for row in roster_rows if row["source_file"] == source_file)
            self.upsert_source(
                source_file,
                self.root / "data" / source_file,
                "staff_roster",
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                supplied_version_key=sample["source_version_key"],
            )

    def load_alias(self) -> None:
        evidence_key = "emails/2026-05-18_outlet_rename.txt"
        sql = """
            INSERT INTO outlet_alias
                (outlet_id, evidence_document_id, alias_code, effective_from,
                 effective_to, validation_status)
            VALUES (%s,%s,'AMK-3A','2026-01-01',NULL,'VERIFIED')
            ON DUPLICATE KEY UPDATE
                outlet_id=VALUES(outlet_id), evidence_document_id=VALUES(evidence_document_id),
                effective_to=VALUES(effective_to), validation_status=VALUES(validation_status)
        """
        with self.connection.cursor() as cursor:
            cursor.execute(sql, (self.outlet_ids["AMK-03"], self.source_ids[evidence_key]))

    def load_daily(self, rows: list[dict[str, str]]) -> None:
        sql = """
            INSERT INTO daily_outlet_summary
                (record_import_key, source_document_id, outlet_id, source_row_number,
                 source_locator, outlet_code_raw, raw_business_date, business_date,
                 raw_sales_amount, sales_amount_sgd, raw_reported_volume, reported_volume,
                 volume_measure, raw_wastage_kg, wastage_kg, remarks, weather,
                 validation_status, validation_notes)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            ON DUPLICATE KEY UPDATE
                source_document_id=VALUES(source_document_id), outlet_id=VALUES(outlet_id),
                source_row_number=VALUES(source_row_number), source_locator=VALUES(source_locator),
                outlet_code_raw=VALUES(outlet_code_raw), raw_business_date=VALUES(raw_business_date),
                business_date=VALUES(business_date), raw_sales_amount=VALUES(raw_sales_amount),
                sales_amount_sgd=VALUES(sales_amount_sgd),
                raw_reported_volume=VALUES(raw_reported_volume),
                reported_volume=VALUES(reported_volume), volume_measure=VALUES(volume_measure),
                raw_wastage_kg=VALUES(raw_wastage_kg), wastage_kg=VALUES(wastage_kg),
                remarks=VALUES(remarks), weather=VALUES(weather),
                validation_status=VALUES(validation_status), validation_notes=VALUES(validation_notes)
        """
        values = []
        for row in rows:
            outlet_code = row["outlet_code_canonical"]
            if outlet_code not in self.outlet_ids:
                raise RuntimeError(f"unknown canonical outlet code: {outlet_code}")
            values.append(
                (
                    row["record_id"], self.source_ids[row["source_file"]],
                    self.outlet_ids[outlet_code], int(row["source_row_number"]),
                    row["source_locator"], row["outlet_code_raw"], row["raw_business_date"],
                    row["business_date"], row["raw_sales_amount"], row["sales_amount_sgd"],
                    row["raw_reported_volume"], int(row["reported_volume"]),
                    row["volume_measure"], nullable(row["raw_wastage_kg"]),
                    nullable(row["wastage_kg"]), nullable(row["remarks"]),
                    nullable(row["weather"]), row["validation_status"],
                    nullable(row["validation_notes"]),
                )
            )
        self.execute_many(sql, values)

    def load_staff_roster(
        self, assignment_rows: list[dict[str, str]], shift_rows: list[dict[str, str]]
    ) -> None:
        if not assignment_rows:
            return
        source_files = {row["source_file"] for row in assignment_rows}
        roster_months = {row["roster_month"] for row in assignment_rows}
        if len(source_files) != 1 or len(roster_months) != 1:
            raise RuntimeError("one loader run must contain one roster source and month")
        source_file = next(iter(source_files))
        roster_month = next(iter(roster_months)) + "-01"
        with self.connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO staff_roster (source_document_id, roster_month, validation_status)
                VALUES (%s,%s,'OK')
                ON DUPLICATE KEY UPDATE
                    staff_roster_id=LAST_INSERT_ID(staff_roster_id),
                    roster_month=VALUES(roster_month),
                    validation_status=VALUES(validation_status)
                """,
                (self.source_ids[source_file], roster_month),
            )
            roster_id = int(cursor.lastrowid)
            assignment_sql = """
                INSERT INTO staff_assignment
                    (assignment_import_key, staff_roster_id, outlet_id, staff_key, staff_name,
                     role, raw_hourly_rate, hourly_rate_sgd, rate_status, source_row_number,
                     source_locator)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                ON DUPLICATE KEY UPDATE
                    staff_assignment_id=LAST_INSERT_ID(staff_assignment_id),
                    outlet_id=VALUES(outlet_id), staff_key=VALUES(staff_key),
                    staff_name=VALUES(staff_name), role=VALUES(role),
                    raw_hourly_rate=VALUES(raw_hourly_rate),
                    hourly_rate_sgd=VALUES(hourly_rate_sgd), rate_status=VALUES(rate_status),
                    source_row_number=VALUES(source_row_number),
                    source_locator=VALUES(source_locator)
            """
            for row in assignment_rows:
                outlet_code = row["outlet_code"]
                if outlet_code not in self.outlet_ids:
                    raise RuntimeError(f"unknown roster outlet code: {outlet_code}")
                cursor.execute(
                    assignment_sql,
                    (
                        row["assignment_id"], roster_id, self.outlet_ids[outlet_code],
                        row["staff_key"], row["staff_name"], row["role"],
                        row["raw_hourly_rate"], nullable(row["hourly_rate_sgd"]),
                        row["rate_status"], int(row["source_row_number"]), row["source_locator"],
                    ),
                )
                self.staff_assignment_ids[row["assignment_id"]] = int(cursor.lastrowid)

        shift_sql = """
            INSERT INTO staff_shift
                (shift_import_key, staff_assignment_id, day_of_week, raw_shift_code,
                 paid_hours, validation_status)
            VALUES (%s,%s,%s,%s,%s,%s)
            ON DUPLICATE KEY UPDATE
                staff_assignment_id=VALUES(staff_assignment_id),
                day_of_week=VALUES(day_of_week), raw_shift_code=VALUES(raw_shift_code),
                paid_hours=VALUES(paid_hours), validation_status=VALUES(validation_status)
        """
        self.execute_many(
            shift_sql,
            [
                (
                    row["shift_id"], self.staff_assignment_ids[row["assignment_id"]],
                    row["day_of_week"], row["raw_shift_code"], nullable(row["paid_hours"]),
                    row["validation_status"],
                )
                for row in shift_rows
            ],
        )

    def load_invoices(
        self, invoice_rows: list[dict[str, str]], item_rows: list[dict[str, str]]
    ) -> None:
        invoice_sql = """
            INSERT INTO supplier_invoice
                (source_document_id, supplier_purchase_id, invoice_number, supplier_name,
                 supplier_address, gst_registration_number, invoice_date, bill_to, subtotal,
                 gst_rate_percent, gst_amount, total_amount, payment_terms, received_condition,
                 mean_ocr_confidence, arithmetic_valid, extraction_status, review_notes)
            VALUES (%s,NULL,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            ON DUPLICATE KEY UPDATE
                supplier_invoice_id=LAST_INSERT_ID(supplier_invoice_id),
                invoice_number=VALUES(invoice_number), supplier_name=VALUES(supplier_name),
                supplier_address=VALUES(supplier_address),
                gst_registration_number=VALUES(gst_registration_number),
                invoice_date=VALUES(invoice_date), bill_to=VALUES(bill_to),
                subtotal=VALUES(subtotal), gst_rate_percent=VALUES(gst_rate_percent),
                gst_amount=VALUES(gst_amount), total_amount=VALUES(total_amount),
                payment_terms=VALUES(payment_terms), received_condition=VALUES(received_condition),
                mean_ocr_confidence=VALUES(mean_ocr_confidence),
                arithmetic_valid=VALUES(arithmetic_valid),
                extraction_status=VALUES(extraction_status), review_notes=VALUES(review_notes)
        """
        with self.connection.cursor() as cursor:
            for row in invoice_rows:
                cursor.execute(
                    invoice_sql,
                    (
                        self.source_ids[row["source_file"]], row["invoice_number"],
                        row["supplier_name"], row["supplier_address"],
                        row["gst_registration_number"], row["invoice_date"], row["bill_to"],
                        row["subtotal"], row["gst_rate_percent"], row["gst_amount"], row["total"],
                        nullable(row["payment_terms"]), nullable(row["received_condition"]),
                        nullable(row["mean_ocr_confidence"]), bool_value(row["arithmetic_valid"]),
                        row["extraction_status"], nullable(row["review_notes"]),
                    ),
                )
                self.invoice_ids[row["invoice_number"]] = int(cursor.lastrowid)

        item_sql = """
            INSERT INTO supplier_invoice_item
                (supplier_invoice_id, line_number, description, quantity, unit_price, amount,
                 mean_field_confidence, line_total_valid, extraction_status, review_notes)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            ON DUPLICATE KEY UPDATE
                description=VALUES(description), quantity=VALUES(quantity),
                unit_price=VALUES(unit_price), amount=VALUES(amount),
                mean_field_confidence=VALUES(mean_field_confidence),
                line_total_valid=VALUES(line_total_valid),
                extraction_status=VALUES(extraction_status), review_notes=VALUES(review_notes)
        """
        values = [
            (
                self.invoice_ids[row["invoice_number"]], int(row["line_number"]),
                nullable(row["description"]), nullable(row["quantity"]),
                nullable(row["unit_price"]), nullable(row["amount"]),
                nullable(row["mean_field_confidence"]), bool_value(row["line_total_valid"]),
                row["extraction_status"], nullable(row["review_notes"]),
            )
            for row in item_rows
        ]
        self.execute_many(item_sql, values)

    def load_purchase_invoice_reconciliation(self) -> None:
        with self.connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT purchase_id, supplier_code, purchase_date, invoice_no, total_amount
                FROM supplier_purchases
                ORDER BY purchase_id
                """
            )
            purchases = list(cursor.fetchall())
            cursor.execute(
                """
                SELECT i.supplier_invoice_id, s.supplier_code, i.invoice_number,
                       i.invoice_date, i.subtotal
                FROM supplier_invoice i
                JOIN supplier s ON UPPER(s.canonical_name)=UPPER(i.supplier_name)
                ORDER BY i.supplier_invoice_id
                """
            )
            invoices = list(cursor.fetchall())

            purchases_by_key: dict[tuple[str, str], list[dict[str, Any]]] = {}
            invoices_by_key: dict[tuple[str, str], list[dict[str, Any]]] = {}
            for purchase in purchases:
                key = (purchase["supplier_code"], purchase["invoice_no"].strip().upper())
                purchases_by_key.setdefault(key, []).append(purchase)
            for invoice in invoices:
                key = (invoice["supplier_code"], invoice["invoice_number"].strip().upper())
                invoices_by_key.setdefault(key, []).append(invoice)

            matches: dict[int, tuple[dict[str, Any], str]] = {}
            for key, candidate_invoices in invoices_by_key.items():
                available_purchases = list(purchases_by_key.get(key, []))
                for invoice in candidate_invoices:
                    if not available_purchases:
                        continue
                    selected = min(
                        available_purchases,
                        key=lambda purchase: (
                            datetime.strptime(purchase["purchase_date"], "%d/%m/%Y").date()
                            != invoice["invoice_date"],
                            abs(Decimal(purchase["total_amount"]) - Decimal(invoice["subtotal"])),
                            purchase["purchase_id"],
                        ),
                    )
                    purchase_date = datetime.strptime(
                        selected["purchase_date"], "%d/%m/%Y"
                    ).date()
                    method = (
                        "SUPPLIER_INVOICE_NUMBER_DATE"
                        if purchase_date == invoice["invoice_date"]
                        else "SUPPLIER_INVOICE_NUMBER_CLOSEST_AMOUNT"
                    )
                    matches[selected["purchase_id"]] = (invoice, method)
                    available_purchases.remove(selected)

            reconciliation_sql = """
                INSERT INTO purchase_invoice_reconciliation
                    (supplier_purchase_id, supplier_invoice_id, reconciliation_status,
                     match_method, legacy_subtotal_sgd, scanned_subtotal_sgd,
                     subtotal_difference_sgd, validation_status)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
                ON DUPLICATE KEY UPDATE
                    supplier_invoice_id=VALUES(supplier_invoice_id),
                    reconciliation_status=VALUES(reconciliation_status),
                    match_method=VALUES(match_method),
                    legacy_subtotal_sgd=VALUES(legacy_subtotal_sgd),
                    scanned_subtotal_sgd=VALUES(scanned_subtotal_sgd),
                    subtotal_difference_sgd=VALUES(subtotal_difference_sgd),
                    validation_status=VALUES(validation_status),
                    reconciled_at=CURRENT_TIMESTAMP
            """
            for purchase in purchases:
                matched = matches.get(purchase["purchase_id"])
                if matched:
                    invoice, method = matched
                    scanned_subtotal = Decimal(invoice["subtotal"])
                    legacy_subtotal = Decimal(purchase["total_amount"])
                    cursor.execute(
                        reconciliation_sql,
                        (
                            purchase["purchase_id"], invoice["supplier_invoice_id"], "MATCHED",
                            method, legacy_subtotal, scanned_subtotal,
                            scanned_subtotal - legacy_subtotal, "CLIENT_RULE_APPLIED",
                        ),
                    )
                    cursor.execute(
                        "UPDATE supplier_invoice SET supplier_purchase_id=%s WHERE supplier_invoice_id=%s",
                        (purchase["purchase_id"], invoice["supplier_invoice_id"]),
                    )
                else:
                    cursor.execute(
                        reconciliation_sql,
                        (
                            purchase["purchase_id"], None, "NO_SCAN", None,
                            purchase["total_amount"], None, None, "CLIENT_RULE_APPLIED",
                        ),
                    )

    def load_chunks(self, rows: list[dict[str, str]]) -> None:
        chunk_sql = """
            INSERT INTO document_chunk
                (chunk_import_key, source_document_id, source_type, occurred_at, author,
                 title, chunk_text, source_locator, embedding_ref)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,NULL)
            ON DUPLICATE KEY UPDATE
                document_chunk_id=LAST_INSERT_ID(document_chunk_id),
                source_document_id=VALUES(source_document_id), source_type=VALUES(source_type),
                occurred_at=VALUES(occurred_at), author=VALUES(author), title=VALUES(title),
                chunk_text=VALUES(chunk_text), source_locator=VALUES(source_locator)
        """
        mention_sql = """
            INSERT INTO document_entity_mention
                (document_chunk_id, resolved_outlet_id, entity_type, mention_text,
                 canonical_key, resolution_status)
            VALUES (%s,%s,%s,%s,%s,%s)
            ON DUPLICATE KEY UPDATE
                resolved_outlet_id=VALUES(resolved_outlet_id),
                mention_text=VALUES(mention_text), resolution_status=VALUES(resolution_status)
        """
        with self.connection.cursor() as cursor:
            for row in rows:
                cursor.execute(
                    chunk_sql,
                    (
                        row["chunk_id"], self.source_ids[row["source_file"]], row["source_type"],
                        local_datetime(row["occurred_at"]), nullable(row["author"]),
                        nullable(row["title"]), row["chunk_text"], row["source_locator"],
                    ),
                )
                chunk_id = int(cursor.lastrowid)
                for code in filter(None, row["mentioned_outlet_codes"].split("|")):
                    resolved = self.outlet_ids.get(code)
                    canonical_code = code
                    if resolved is None:
                        cursor.execute(
                            """
                            SELECT a.outlet_id, o.outlet_code
                            FROM outlet_alias a
                            JOIN outlets o ON o.outlet_id = a.outlet_id
                            WHERE a.alias_code = %s
                              AND a.validation_status = 'VERIFIED'
                            ORDER BY a.effective_from DESC
                            LIMIT 1
                            """,
                            (code,),
                        )
                        alias = cursor.fetchone()
                        if alias:
                            resolved = alias["outlet_id"]
                            canonical_code = alias["outlet_code"]
                    cursor.execute(
                        mention_sql,
                        (
                            chunk_id, resolved, "outlet", code,
                            canonical_code,
                            "RESOLVED" if resolved else "UNRESOLVED",
                        ),
                    )
                for supplier in filter(None, row["mentioned_suppliers"].split("|")):
                    cursor.execute(
                        mention_sql,
                        (chunk_id, None, "supplier", supplier, supplier, "CANONICALIZED"),
                    )

    def load_quality_issues(
        self,
        quality_rows: list[dict[str, str]],
        invoice_rows: list[dict[str, str]],
        item_rows: list[dict[str, str]],
        roster_issue_rows: list[dict[str, str]],
    ) -> None:
        sql = """
            INSERT INTO data_quality_issue
                (issue_import_key, source_document_id, record_type, record_key,
                 source_locator, rule_code, severity, details, resolution_status)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
            ON DUPLICATE KEY UPDATE
                source_document_id=VALUES(source_document_id), record_type=VALUES(record_type),
                record_key=VALUES(record_key), source_locator=VALUES(source_locator),
                rule_code=VALUES(rule_code), severity=VALUES(severity), details=VALUES(details),
                resolution_status=VALUES(resolution_status)
        """
        values: list[tuple[Any, ...]] = []
        for row in quality_rows:
            record_key = f"{row['outlet_code']}:{row['business_date']}"
            values.append(
                (
                    row["issue_id"], self.source_ids[row["source_file"]],
                    "daily_outlet_summary", record_key, nullable(row["source_locator"]),
                    row["rule_code"], row["severity"], row["details"], row["resolution_status"],
                )
            )
        for row in invoice_rows:
            if row["extraction_status"] == "OK":
                continue
            values.append(
                (
                    stable_key("dq", row["source_file"], "invoice"),
                    self.source_ids[row["source_file"]], "supplier_invoice",
                    row["invoice_number"], None, "INVOICE_REVIEW_REQUIRED", "WARNING",
                    row["review_notes"] or "Invoice extraction requires review.", "OPEN",
                )
            )
        for row in item_rows:
            if row["extraction_status"] == "OK":
                continue
            values.append(
                (
                    stable_key("dq", row["source_file"], "item", row["line_number"]),
                    self.source_ids[row["source_file"]], "supplier_invoice_item",
                    f"{row['invoice_number']}:{row['line_number']}", None,
                    "INVOICE_ITEM_REVIEW_REQUIRED", "WARNING",
                    row["review_notes"] or "Invoice item extraction requires review.", "OPEN",
                )
            )
        for row in roster_issue_rows:
            values.append(
                (
                    row["issue_id"], self.source_ids[row["source_file"]], "staff_roster",
                    row["record_key"], nullable(row["source_locator"]), row["rule_code"],
                    row["severity"], row["details"], row["resolution_status"],
                )
            )
        self.execute_many(sql, values)

    def verify(self) -> dict[str, int]:
        tables = [
            "source_document", "outlet_alias", "daily_outlet_summary", "supplier",
            "supplier_invoice",
            "supplier_invoice_item", "document_chunk", "document_entity_mention",
            "purchase_invoice_reconciliation", "staff_roster", "staff_assignment",
            "staff_shift", "data_quality_issue",
        ]
        counts: dict[str, int] = {}
        with self.connection.cursor() as cursor:
            for table in tables:
                cursor.execute(f"SELECT COUNT(*) AS count FROM {table}")
                counts[table] = int(cursor.fetchone()["count"])
            cursor.execute(
                """
                SELECT COUNT(*) AS count
                FROM daily_outlet_summary d
                LEFT JOIN source_document s ON s.source_document_id=d.source_document_id
                LEFT JOIN outlets o ON o.outlet_id=d.outlet_id
                WHERE s.source_document_id IS NULL OR o.outlet_id IS NULL
                """
            )
            counts["broken_daily_links"] = int(cursor.fetchone()["count"])
        return counts


def main() -> int:
    args = parse_args()
    root = args.project_root.expanduser().resolve()
    try:
        import pymysql
        from pymysql.cursors import DictCursor
    except ModuleNotFoundError:
        raise SystemExit(
            "error: PyMySQL is not installed; run "
            "'.venv/bin/python -m pip install -r ingestion/requirements-db.txt'"
        )

    structured = root / "runtime" / "structured"
    daily_rows = read_csv(structured / "daily_outlet_summaries.csv")
    invoice_rows = read_csv(structured / "invoices.csv")
    item_rows = read_csv(structured / "invoice_items.csv")
    chunk_rows = read_csv(structured / "document_chunks.csv")
    quality_rows = read_csv(structured / "tabular_quality_issues.csv")
    roster_rows = read_csv(structured / "staff_roster_assignments.csv")
    roster_shift_rows = read_csv(structured / "staff_roster_shifts.csv")
    roster_issue_rows = read_csv(structured / "staff_roster_quality_issues.csv")

    connection = pymysql.connect(
        host=args.host, port=args.port, user=args.user, password=args.password,
        database=args.database, charset="utf8mb4", cursorclass=DictCursor, autocommit=False,
    )
    try:
        loader = Loader(connection, root)
        loader.load_outlets()
        loader.load_suppliers()
        loader.load_source_documents(daily_rows, invoice_rows, chunk_rows, roster_rows)
        loader.load_alias()
        loader.load_daily(daily_rows)
        loader.load_staff_roster(roster_rows, roster_shift_rows)
        loader.load_invoices(invoice_rows, item_rows)
        loader.load_purchase_invoice_reconciliation()
        loader.load_chunks(chunk_rows)
        loader.load_quality_issues(
            quality_rows, invoice_rows, item_rows, roster_issue_rows
        )
        counts = loader.verify()
        if counts["broken_daily_links"]:
            raise RuntimeError(f"found {counts['broken_daily_links']} broken daily-summary links")
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()

    for table, count in counts.items():
        print(f"{table}: {count}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
