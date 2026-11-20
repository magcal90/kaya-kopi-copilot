"""Live MySQL contract for the normalized June 2026 roster."""

from __future__ import annotations

import unittest
from unittest.mock import ANY

import pymysql
from pymysql.cursors import DictCursor

from app.repositories.mysql import DatabaseConfig


class RosterIngestionIntegrationTest(unittest.TestCase):
    def test_roster_is_loaded_with_lineage_and_normalized_shift_rules(self) -> None:
        config = DatabaseConfig.from_env()
        with pymysql.connect(
            host=config.host,
            port=config.port,
            user=config.user,
            password=config.password,
            database=config.database,
            cursorclass=DictCursor,
        ) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT r.roster_month, s.source_uri,
                           COUNT(DISTINCT a.staff_assignment_id) AS assignments,
                           COUNT(sh.staff_shift_id) AS shifts,
                           COUNT(DISTINCT a.outlet_id) AS outlets,
                           SUM(a.rate_status='CLIENT_APPROVED_DEFAULT') AS defaulted_rates
                    FROM staff_roster r
                    JOIN source_document s ON s.source_document_id=r.source_document_id
                    JOIN staff_assignment a ON a.staff_roster_id=r.staff_roster_id
                    JOIN staff_shift sh ON sh.staff_assignment_id=a.staff_assignment_id
                    GROUP BY r.staff_roster_id, r.roster_month, s.source_uri
                    """
                )
                row = cursor.fetchone()
                self.assertIsNotNone(row)
                self.assertEqual(row["roster_month"].isoformat(), "2026-06-01")
                self.assertEqual(row["source_uri"], "data/tabular/staff_roster_jun2026.xlsx")
                self.assertEqual(row["assignments"], 46)
                self.assertEqual(row["shifts"], 322)
                self.assertEqual(row["outlets"], 12)
                self.assertGreater(row["defaulted_rates"], 0)

                cursor.execute(
                    "SELECT raw_shift_code, paid_hours FROM staff_shift GROUP BY raw_shift_code, paid_hours"
                )
                self.assertEqual(
                    {(row["raw_shift_code"], f'{row["paid_hours"]:.2f}') for row in cursor.fetchall()},
                    {("AM", "7.00"), ("PM", "7.00"), ("AM/PM", "13.00"), ("OFF", "0.00")},
                )

    def test_reused_invoice_number_keeps_both_purchases_and_matches_one_scan_by_date(self) -> None:
        config = DatabaseConfig.from_env()
        with pymysql.connect(
            host=config.host,
            port=config.port,
            user=config.user,
            password=config.password,
            database=config.database,
            cursorclass=DictCursor,
        ) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT r.supplier_purchase_id, r.supplier_invoice_id,
                           r.reconciliation_status, r.match_method
                    FROM purchase_invoice_reconciliation r
                    JOIN supplier_purchases p ON p.purchase_id=r.supplier_purchase_id
                    WHERE p.invoice_no='INV-042509-752'
                    ORDER BY r.supplier_purchase_id
                    """
                )
                self.assertEqual(
                    list(cursor.fetchall()),
                    [
                        {
                            "supplier_purchase_id": 5040,
                            "supplier_invoice_id": None,
                            "reconciliation_status": "NO_SCAN",
                            "match_method": None,
                        },
                        {
                            "supplier_purchase_id": 5041,
                            "supplier_invoice_id": ANY,
                            "reconciliation_status": "MATCHED",
                            "match_method": "SUPPLIER_INVOICE_NUMBER_DATE",
                        },
                    ],
                )


if __name__ == "__main__":
    unittest.main()
