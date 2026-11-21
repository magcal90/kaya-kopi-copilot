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
        self.assertEqual(
            result["result_contract"],
            {
                "kind": "COMPLETE_AGGREGATE",
                "complete_for_claim": True,
                "truncated": False,
                "claim_scope": "OBSERVED_POS_ROWS",
            },
        )
        self.assertGreater(sum(int(row["quantity"]) for row in result["results"]), 0)

    def test_analyze_suppliers_spend_uses_canonical_invoice_cost(self) -> None:
        result = analyze_suppliers.invoke({"analysis": "spend", "group_by": "supplier"})
        self.assertTrue(result["ok"], result)
        self.assertEqual(result["authority"], "SCANNED_INVOICE_CANONICAL_COST")
        self.assertEqual(sum(int(row["invoice_count"]) for row in result["results"]), 68)
        self.assertEqual(result["excluded_review_required_invoices"], 1)
        self.assertEqual(
            result["result_contract"],
            {
                "kind": "COMPLETE_AGGREGATE",
                "complete_for_claim": True,
                "truncated": False,
                "claim_scope": "VALIDATED_SCANNED_INVOICES",
            },
        )

    def test_analyze_suppliers_spend_identifies_excluded_invoice(self) -> None:
        result = analyze_suppliers.invoke(
            {
                "analysis": "spend",
                "start_date": "2025-07-01",
                "end_date": "2026-06-30",
                "group_by": "supplier_month",
            }
        )

        self.assertTrue(result["ok"], result)
        self.assertEqual(result["included_invoice_count"], 68)
        self.assertEqual(result["excluded_invoice_count"], 1)
        self.assertEqual(
            result["excluded_invoices"],
            [
                {
                    "invoice_number": "INV-012601-458",
                    "supplier_name": "HENG HUAT COFFEE ROASTERS",
                    "invoice_date": "2026-01-21",
                    "reason": "REVIEW_REQUIRED",
                    "source_uri": "data/images/supplier_invoices/INV-012601-458.jpg",
                }
            ],
        )

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

    def test_supplier_price_change_identifies_largest_comparable_increase_with_evidence(self) -> None:
        result = analyze_suppliers.invoke(
            {
                "analysis": "price_change",
                "start_date": "2025-07-01",
                "end_date": "2026-06-30",
            }
        )

        self.assertTrue(result["ok"], result)
        self.assertEqual(result["status"], "COMPLETE")
        self.assertGreater(result["comparable_series_count"], 0)
        self.assertEqual(result["insufficient_series_count"], 0)
        largest = result["largest_increase"]
        self.assertEqual(largest["supplier_code"], "SUP-04")
        self.assertEqual(largest["supplier_name"], "MEWAH SUGAR TRADING")
        self.assertEqual(largest["description"], "Condensed milk ctn")
        self.assertEqual(largest["first_unit_price_sgd"], "43.8000")
        self.assertEqual(largest["latest_unit_price_sgd"], "50.4700")
        self.assertEqual(largest["percent_change"], "15.23")
        self.assertIn("invoice_number", largest["first_evidence"])
        self.assertIn("citation", largest["first_evidence"])
        self.assertIn("invoice_number", largest["latest_evidence"])
        self.assertIn("citation", largest["latest_evidence"])
        self.assertEqual(result["result_contract"]["kind"], "PAGED_DETAIL")
        self.assertFalse(result["result_contract"]["complete_for_claim"])
        self.assertLessEqual(len(result["results"]), 50)
        self.assertEqual(result["result_contract"]["has_more"], False)

    def test_supplier_price_change_series_are_paginated_after_full_sql_ranking(self) -> None:
        first = analyze_suppliers.invoke(
            {
                "analysis": "price_change",
                "start_date": "2025-07-01",
                "end_date": "2026-06-30",
                "detail_limit": 1,
            }
        )
        self.assertTrue(first["ok"], first)
        self.assertEqual(len(first["results"]), 1)
        self.assertTrue(first["result_contract"]["has_more"])
        self.assertFalse(first["result_contract"]["complete_for_claim"])
        cursor = first["result_contract"]["next_cursor"]
        self.assertTrue(cursor)

        second = analyze_suppliers.invoke(
            {
                "analysis": "price_change",
                "start_date": "2025-07-01",
                "end_date": "2026-06-30",
                "detail_limit": 1,
                "series_cursor": cursor,
            }
        )
        self.assertTrue(second["ok"], second)
        self.assertEqual(len(second["results"]), 1)
        self.assertNotEqual(first["results"][0]["series_key"], second["results"][0]["series_key"])
        self.assertFalse(second["result_contract"]["complete_for_claim"])

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

    def test_supplier_reconciliation_pages_detail_without_implying_completeness(self) -> None:
        first = analyze_suppliers.invoke(
            {
                "analysis": "reconciliation",
                "invoice_number": "INV-042509-752",
                "detail_limit": 1,
            }
        )

        self.assertTrue(first["ok"], first)
        self.assertEqual(len(first["results"]), 1)
        self.assertEqual(first["result_contract"]["kind"], "PAGED_DETAIL")
        self.assertFalse(first["result_contract"]["complete_for_claim"])
        self.assertTrue(first["result_contract"]["has_more"])
        cursor = first["result_contract"]["next_cursor"]
        self.assertIsNotNone(cursor)

        second = analyze_suppliers.invoke(
            {
                "analysis": "reconciliation",
                "invoice_number": "INV-042509-752",
                "detail_limit": 1,
                "after_purchase_id": cursor,
            }
        )

        self.assertTrue(second["ok"], second)
        self.assertEqual(len(second["results"]), 1)
        self.assertNotEqual(
            first["results"][0]["supplier_purchase_id"],
            second["results"][0]["supplier_purchase_id"],
        )
        self.assertFalse(second["result_contract"]["has_more"])
        self.assertFalse(second["result_contract"]["complete_for_claim"])

    def test_reconciliation_distinguishes_identity_match_from_amount_match_and_gst(self) -> None:
        result = analyze_suppliers.invoke(
            {"analysis": "reconciliation", "invoice_number": "INV-012508-182"}
        )

        self.assertTrue(result["ok"], result)
        row = result["results"][0]
        self.assertTrue(row["identity_match"])
        self.assertFalse(row["amount_match"])
        self.assertEqual(row["legacy_subtotal_sgd"], "942.00")
        self.assertEqual(row["scanned_subtotal_sgd"], "951.33")
        self.assertEqual(row["subtotal_difference_sgd"], "9.33")
        self.assertFalse(row["gst_responsible"])
        self.assertEqual(row["cause"], "UNDETERMINED")
        self.assertEqual(
            row["gst_explanation"],
            "GST cannot explain this difference because both compared values are pre-GST subtotals.",
        )
        self.assertTrue(result["invoice_evidence"]["found"])
        self.assertTrue(result["invoice_evidence"]["items"])

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
        self.assertEqual(
            result["result_contract"],
            {
                "kind": "COMPLETE_AGGREGATE",
                "complete_for_claim": True,
                "truncated": False,
                "claim_scope": "REPORTED_SOURCE_ROWS",
            },
        )

    def test_analyze_outlets_preserves_alias_resolution_evidence(self) -> None:
        result = analyze_outlets.invoke(
            {
                "analysis": "performance",
                "outlet_codes": ["AMK-3A"],
                "start_date": "2026-01-01",
                "end_date": "2026-01-31",
            }
        )

        self.assertTrue(result["ok"], result)
        row = result["results"][0]
        self.assertEqual(row["requested_outlet_code"], "AMK-3A")
        self.assertEqual(row["outlet_code"], "AMK-03")
        self.assertEqual(row["alias_resolution"]["canonical_code"], "AMK-03")
        self.assertEqual(
            row["alias_resolution"]["evidence_source_uri"],
            "data/docs/emails/2026-05-18_outlet_rename.txt",
        )

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

    def test_analyze_outlets_wastage_ranks_only_measured_outlets(self) -> None:
        result = analyze_outlets.invoke(
            {
                "analysis": "wastage",
                "outlet_codes": [],
                "start_date": "2025-07-01",
                "end_date": "2026-06-30",
            }
        )

        self.assertTrue(result["ok"], result)
        self.assertEqual(result["status"], "PARTIAL")
        self.assertFalse(result["all_outlets_comparable"])
        self.assertEqual(result["comparison_scope"], "MEASURED_OUTLETS_ONLY")
        self.assertEqual(result["measured_outlet_count"], 2)
        self.assertEqual(result["highest_measured_wastage"]["outlet_code"], "BDK-01")
        self.assertEqual(result["highest_measured_wastage"]["total_wastage_kg"], "640.400")
        self.assertEqual(
            [row["outlet_code"] for row in result["ranked_measured_results"]],
            ["BDK-01", "WDL-01"],
        )

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

    def test_analyze_outlets_staffing_does_not_invent_overstaffing_threshold(self) -> None:
        result = analyze_outlets.invoke(
            {
                "analysis": "staffing",
                "outlet_codes": [],
                "start_date": "2026-06-01",
                "end_date": "2026-06-30",
            }
        )

        self.assertTrue(result["ok"], result)
        self.assertEqual(result["classification"], "NO_APPROVED_OVERSTAFFING_THRESHOLD")
        self.assertEqual(result["lowest_comparable_productivity"]["outlet_code"], "BDK-01")
        self.assertEqual(
            {row["outlet_code"] for row in result["non_comparable_outlets"]},
            {"JEM-01", "ORC-01", "PGL-01", "VIV-01"},
        )
        self.assertTrue(
            all(row["productivity_comparable"] for row in result["comparable_outlets"])
        )

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

    def test_monthly_sales_aggregate_is_exact_without_row_level_payload(self) -> None:
        result = get_outlet_sales.invoke(
            {
                "outlet_code": "AMK-01",
                "start_date": "2025-07-01",
                "end_date": "2025-07-31",
                "include_daily": False,
            }
        )

        self.assertTrue(result["ok"], result)
        self.assertEqual(result["summary"]["gross_takings_sgd"], "26159.57")
        self.assertEqual(result["summary"]["receipt_count"], 8427)
        self.assertEqual(result["summary"]["reported_days"], 27)
        self.assertEqual(result["coverage"]["missing_dates"], [
            "2025-07-07", "2025-07-08", "2025-07-11", "2025-07-12"
        ])
        self.assertEqual(
            result["result_contract"],
            {
                "kind": "COMPLETE_AGGREGATE",
                "complete_for_claim": True,
                "truncated": False,
                "claim_scope": "REPORTED_SOURCE_ROWS",
            },
        )
        self.assertNotIn("records", result["citation"])
        self.assertEqual(result["citation"]["record_count"], 27)

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
        self.assertEqual(result["aggregate_contract"]["kind"], "COMPLETE_AGGREGATE")
        self.assertEqual(result["evidence_contract"]["kind"], "PAGED_DETAIL")
        self.assertFalse(result["evidence_contract"]["complete_for_claim"])

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
