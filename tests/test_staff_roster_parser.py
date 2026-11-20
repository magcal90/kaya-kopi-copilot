"""Behavior tests for the client-supplied June 2026 staff roster."""

from __future__ import annotations

import unittest
from pathlib import Path

from ingestion.parsers.staff_roster import parse_roster


class StaffRosterParserTest(unittest.TestCase):
    def test_real_roster_normalizes_client_confirmed_shift_and_rate_rules(self) -> None:
        root = Path(__file__).resolve().parents[1]

        parsed = parse_roster(root / "data" / "tabular" / "staff_roster_jun2026.xlsx")

        self.assertEqual(parsed.roster_month, "2026-06")
        self.assertEqual(len(parsed.assignments), 46)
        self.assertEqual(len(parsed.shifts), 322)
        self.assertEqual(
            {row["outlet_code"] for row in parsed.assignments},
            {
                "AMK-01", "AMK-03", "BDK-01", "JEM-01", "JUR-01", "ORC-01",
                "PGL-01", "TAM-01", "TPY-02", "VIV-01", "WDL-01", "YIS-02",
            },
        )
        self.assertEqual(
            {(row["raw_shift_code"], row["paid_hours"]) for row in parsed.shifts},
            {("AM", "7.00"), ("PM", "7.00"), ("AM/PM", "13.00"), ("OFF", "0.00")},
        )
        defaults = [
            row for row in parsed.assignments if row["rate_status"] == "CLIENT_APPROVED_DEFAULT"
        ]
        self.assertTrue(defaults)
        self.assertTrue(all(row["raw_hourly_rate"] == "TBC" for row in defaults))
        self.assertTrue(all(row["hourly_rate_sgd"] == "13.00" for row in defaults))
        self.assertTrue(all(row["source_locator"].startswith("sheet=Roster Jun 2026;row=") for row in parsed.assignments))
        self.assertEqual(parsed.issues, [])


if __name__ == "__main__":
    unittest.main()
