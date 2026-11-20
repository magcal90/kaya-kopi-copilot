"""Behavior tests for heterogeneous daily-summary normalization."""

from __future__ import annotations

import unittest
from pathlib import Path

from ingestion.parsers.tabular import normalize_file


class TabularParserTest(unittest.TestCase):
    def test_client_confirmed_labels_normalize_to_gross_takings_and_receipts(self) -> None:
        root = Path(__file__).resolve().parents[1]
        input_dir = root / "data" / "tabular"
        records = []
        for path in sorted(input_dir.glob("daily_summary_*.csv")):
            file_records, _issues = normalize_file(path, input_dir)
            records.extend(file_records)

        self.assertEqual(
            {row["source_sales_label"] for row in records},
            {"Total Sales (SGD)", "sales$", "REVENUE", "Gross Takings"},
        )
        self.assertEqual(
            {row["source_volume_label"] for row in records},
            {"No of Cups", "txns", "CUPS", "Customer Count"},
        )
        self.assertEqual({row["volume_measure"] for row in records}, {"receipts"})
        self.assertTrue(all(row["gross_takings_sgd"] == row["sales_amount_sgd"] for row in records))


if __name__ == "__main__":
    unittest.main()
