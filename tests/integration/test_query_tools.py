"""Live MySQL smoke tests for the six chatbot query tools."""

from __future__ import annotations

import unittest

from app.tools.kaya import (
    ALL_TOOLS,
    analyze_pos,
    analyze_outlets,
    analyze_suppliers,
    assess_kopi_price_change,
    compare_outlets,
    get_data_quality_issues,
    get_data_coverage,
    get_invoice,
    get_outlet_sales,
    get_supplier_cost_trend,
    search_documents,
)


class QueryToolIntegrationTest(unittest.TestCase):
    def test_public_tool_set_is_consolidated(self) -> None:
        self.assertEqual(
            [tool.name for tool in ALL_TOOLS],
            ["analyze_outlets", "analyze_pos", "analyze_suppliers", "get_data_coverage", "search_documents", "assess_kopi_price_change", "get_data_quality_issues"],
        )

    def test_analyze_pos_product_mix_is_explicitly_partial(self) -> None:
        result = analyze_pos.invoke({"analysis": "product_mix", "outlet_codes": ["AMK-01"], "start_date": "2025-07-01", "end_date": "2026-06-30", "menu_item": "Kopi"})
        self.assertTrue(result["ok"], result)
        self.assertEqual(result["authority"], "PARTIAL_POS_EXPORT")
        self.assertGreater(sum(int(row["quantity"]) for row in result["results"]), 0)

    def test_analyze_suppliers_spend_uses_canonical_invoice_cost(self) -> None:
        result = analyze_suppliers.invoke({"analysis": "spend", "group_by": "supplier"})
        self.assertTrue(result["ok"], result)
        self.assertEqual(result["authority"], "SCANNED_INVOICE_CANONICAL_COST")
        self.assertEqual(sum(int(row["invoice_count"]) for row in result["results"]), 68)
        self.assertEqual(result["excluded_review_required_invoices"], 1)

    def test_analyze_suppliers_returns_2025_invoice_totals_by_month(self) -> None:
        result = analyze_suppliers.invoke(
            {
                "analysis": "spend",
                "start_date": "2025-01-01",
                "end_date": "2025-12-31",
                "group_by": "month",
            }
        )

        self.assertTrue(result["ok"], result)
        self.assertTrue(result["results"])
        self.assertTrue(all(row["month"].startswith("2025-") for row in result["results"]))
        self.assertGreater(
            sum(float(row["total_sgd"]) for row in result["results"]),
            0,
        )

    def test_analyze_suppliers_reconciliation_keeps_reused_invoice_number(self) -> None:
        result = analyze_suppliers.invoke(
            {"analysis": "reconciliation", "invoice_number": "INV-042509-752"}
        )
        self.assertTrue(result["ok"], result)
        self.assertEqual(len(result["results"]), 2)
        self.assertEqual(
            {row["reconciliation_status"] for row in result["results"]},
            {"MATCHED", "NO_SCAN"},
        )

    def test_data_coverage_reports_known_source_counts(self) -> None:
        result = get_data_coverage.invoke({"area": "all"})
        self.assertTrue(result["ok"], result)
        self.assertEqual(result["sections"]["sales"]["outlet_count"], 12)
        self.assertEqual(result["sections"]["sales"]["outlets_with_daily_summaries"], 8)
        self.assertEqual(result["sections"]["invoices"]["scanned_invoices"], 69)
        self.assertEqual(result["sections"]["staffing"]["assignments"], 46)

    def test_kopi_price_assessment_refuses_to_overstate_partial_evidence(self) -> None:
        result = assess_kopi_price_change.invoke({"menu_scope": "base_kopi", "start_date": "2025-07-01", "end_date": "2026-06-30", "gross_price_increase_sgd": "0.10", "demand_change_percent": ["0"]})
        self.assertTrue(result["ok"], result)
        self.assertEqual(result["recommendation"], "INSUFFICIENT_EVIDENCE")
        self.assertEqual(result["status"], "PARTIAL")
        self.assertGreater(int(result["observed_partial_pos"]["units"]), 0)
    def test_analyze_outlets_performance_uses_authoritative_daily_summary(self) -> None:
        result = analyze_outlets.invoke(
            {
                "analysis": "performance",
                "outlet_codes": ["AMK-01"],
                "start_date": "2025-07-01",
                "end_date": "2025-07-01",
            }
        )

        self.assertTrue(result["ok"], result)
        self.assertEqual(result["analysis"], "performance")
        self.assertEqual(result["results"][0]["authority"], "DAILY_SUMMARY_Z_REPORT")
        self.assertEqual(result["results"][0]["gross_takings_sgd"], "815.51")
        self.assertEqual(result["results"][0]["receipt_count"], 263)

    def test_analyze_outlets_wastage_discloses_unrecorded_outlets(self) -> None:
        result = analyze_outlets.invoke(
            {
                "analysis": "wastage",
                "outlet_codes": ["BDK-01", "JUR-01"],
                "start_date": "2025-07-01",
                "end_date": "2026-06-30",
            }
        )

        self.assertTrue(result["ok"], result)
        by_outlet = {row["outlet_code"]: row for row in result["results"]}
        self.assertEqual(by_outlet["BDK-01"]["coverage_status"], "MEASURED")
        self.assertGreater(by_outlet["BDK-01"]["measured_days"], 0)
        self.assertEqual(by_outlet["JUR-01"]["coverage_status"], "NOT_RECORDED")
        self.assertIsNone(by_outlet["JUR-01"]["total_wastage_kg"])

    def test_analyze_outlets_staffing_expands_weekly_roster_and_labels_revenue_coverage(self) -> None:
        result = analyze_outlets.invoke(
            {
                "analysis": "staffing",
                "outlet_codes": ["AMK-01", "ORC-01"],
                "start_date": "2026-06-01",
                "end_date": "2026-06-30",
            }
        )

        self.assertTrue(result["ok"], result)
        by_outlet = {row["outlet_code"]: row for row in result["results"]}
        self.assertGreater(float(by_outlet["AMK-01"]["paid_hours"]), 0)
        self.assertGreater(float(by_outlet["AMK-01"]["labour_cost_sgd"]), 0)
        self.assertEqual(by_outlet["AMK-01"]["revenue_authority"], "DAILY_SUMMARY_Z_REPORT")
        self.assertTrue(by_outlet["AMK-01"]["productivity_comparable"])
        self.assertEqual(by_outlet["ORC-01"]["revenue_authority"], "PARTIAL_POS_EXPORT")
        self.assertFalse(by_outlet["ORC-01"]["productivity_comparable"])

    def test_get_outlet_sales_uses_authoritative_daily_summary_when_available(self) -> None:
        result = get_outlet_sales.invoke(
            {
                "outlet_code": "AMK-01",
                "start_date": "2025-07-01",
                "end_date": "2025-07-01",
                "include_daily": False,
            }
        )

        self.assertTrue(result["ok"], result)
        self.assertEqual(result["authority"], "DAILY_SUMMARY_Z_REPORT")
        self.assertEqual(result["summary"]["gross_takings_sgd"], "815.51")
        self.assertEqual(result["summary"]["receipt_count"], 263)
        self.assertEqual(result["coverage"]["missing_dates"], [])

    def test_get_outlet_sales(self) -> None:
        result = get_outlet_sales.invoke(
            {
                "outlet_code": "AMK-03",
                "start_date": "2026-01-01",
                "end_date": "2026-01-31",
                "include_daily": False,
            }
        )
        self.assertTrue(result["ok"], result)
        self.assertEqual(result["outlet_code"], "AMK-03")
        self.assertGreater(result["summary"]["transaction_count"], 0)

    def test_get_outlet_sales_explains_database_backed_alias(self) -> None:
        result = get_outlet_sales.invoke(
            {
                "outlet_code": "AMK-3A",
                "start_date": "2026-01-01",
                "end_date": "2026-01-31",
                "include_daily": False,
            }
        )

        self.assertTrue(result["ok"], result)
        self.assertEqual(result["outlet_code"], "AMK-03")
        self.assertEqual(
            result["alias_resolution"],
            {
                "requested_code": "AMK-3A",
                "canonical_code": "AMK-03",
                "effective_from": "2026-01-01",
                "effective_to": None,
                "validation_status": "VERIFIED",
                "evidence_source_uri": "data/docs/emails/2026-05-18_outlet_rename.txt",
            },
        )

    def test_compare_outlets(self) -> None:
        result = compare_outlets.invoke(
            {
                "outlet_codes": ["AMK-01", "AMK-03", "JUR-01"],
                "start_date": "2025-07-01",
                "end_date": "2025-07-31",
            }
        )
        self.assertTrue(result["ok"], result)
        self.assertEqual(result["authority"], "DAILY_SUMMARY_Z_REPORT")
        self.assertEqual(len(result["comparison"]), 3)
        self.assertEqual([row["sales_rank"] for row in result["comparison"]], [1, 2, 3])

    def test_get_invoice(self) -> None:
        result = get_invoice.invoke({"invoice_number": "INV-012508-182"})
        self.assertTrue(result["ok"], result)
        self.assertTrue(result["found"])
        self.assertEqual(len(result["items"]), 2)
        self.assertIn("source_uri", result["citation"])

    def test_get_invoice_uses_validated_lines_when_header_arithmetic_is_invalid(self) -> None:
        result = get_invoice.invoke({"invoice_number": "INV-032603-511"})

        self.assertTrue(result["ok"], result)
        self.assertEqual(
            result["canonical_cost"],
            {
                "subtotal_sgd": "179.07",
                "gst_sgd": "16.12",
                "total_sgd": "195.19",
                "cost_basis": "VALIDATED_INVOICE_LINES",
                "review_required": True,
                "header_arithmetic_valid": False,
            },
        )

    def test_get_supplier_cost_trend(self) -> None:
        result = get_supplier_cost_trend.invoke(
            {
                "supplier_name": "Mewah",
                "start_date": "2025-07-01",
                "end_date": "2026-06-30",
            }
        )
        self.assertTrue(result["ok"], result)
        self.assertEqual(result["matched_suppliers"], ["MEWAH SUGAR TRADING"])
        self.assertEqual(result["matched_supplier_codes"], ["SUP-04"])
        self.assertTrue(result["monthly"])
        self.assertTrue(all("citation" in row for row in result["evidence"]))

    def test_search_documents(self) -> None:
        result = search_documents.invoke(
            {"query": "fridge spoil", "outlet_code": "TAM-01", "limit": 3}
        )
        self.assertTrue(result["ok"], result)
        self.assertTrue(result["results"])
        self.assertTrue(all("citation" in row for row in result["results"]))

    def test_search_documents_with_supplier_filter(self) -> None:
        result = search_documents.invoke(
            {"query": "eggs deliver", "supplier_name": "Ban Seng", "limit": 3}
        )
        self.assertTrue(result["ok"], result)
        self.assertTrue(result["results"])

    def test_get_data_quality_issues(self) -> None:
        result = get_data_quality_issues.invoke(
            {"status": "OPEN", "severity": "WARNING", "limit": 5}
        )
        self.assertTrue(result["ok"], result)
        self.assertEqual(result["count"], 5)
        self.assertTrue(all("citation" in row for row in result["issues"]))

    def test_validation_error_is_safe(self) -> None:
        result = get_outlet_sales.invoke(
            {
                "outlet_code": "BAD-99",
                "start_date": "2026-01-01",
                "end_date": "2026-01-31",
                "include_daily": False,
            }
        )
        self.assertFalse(result["ok"])
        self.assertEqual(result["error_type"], "validation")


if __name__ == "__main__":
    unittest.main()
