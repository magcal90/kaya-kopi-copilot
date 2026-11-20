"""Validated LangChain interfaces for Kaya Kopi business and retrieval queries."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from functools import lru_cache
from typing import Any, Literal

import pymysql
from langchain_core.tools import tool
from pydantic import BaseModel, Field

from app.repositories.mysql import MySQLRepository


class OutletSalesInput(BaseModel):
    outlet_code: str = Field(description="Canonical outlet code, for example AMK-03 or JUR-01")
    start_date: date = Field(description="Inclusive start date in YYYY-MM-DD format")
    end_date: date = Field(description="Inclusive end date in YYYY-MM-DD format")
    include_daily: bool = Field(default=True, description="Include daily results as well as totals")


class CompareOutletsInput(BaseModel):
    outlet_codes: list[str] = Field(
        min_length=2, max_length=12, description="Two or more canonical outlet codes to compare"
    )
    start_date: date = Field(description="Inclusive start date in YYYY-MM-DD format")
    end_date: date = Field(description="Inclusive end date in YYYY-MM-DD format")


class InvoiceInput(BaseModel):
    invoice_number: str = Field(description="Invoice number such as INV-012508-182")


class SupplierTrendInput(BaseModel):
    supplier_name: str = Field(description="Full or partial supplier name")
    start_date: date = Field(description="Inclusive invoice start date in YYYY-MM-DD format")
    end_date: date = Field(description="Inclusive invoice end date in YYYY-MM-DD format")


class DocumentSearchInput(BaseModel):
    query: str = Field(description="Natural-language or keyword query")
    limit: int = Field(default=5, ge=1, le=10)
    outlet_code: str | None = Field(default=None, description="Optional canonical outlet filter")
    supplier_name: str | None = Field(default=None, description="Optional supplier-name filter")


class QualityIssuesInput(BaseModel):
    status: str = Field(default="OPEN", description="Resolution status, usually OPEN")
    severity: str | None = Field(default=None, description="Optional ERROR, WARNING, or INFO filter")
    rule_code: str | None = Field(default=None, description="Optional exact quality rule code")
    limit: int = Field(default=50, ge=1, le=100)


class AnalyzeOutletsInput(BaseModel):
    analysis: Literal["performance", "wastage", "staffing"]
    outlet_codes: list[str] = Field(default_factory=list, max_length=12)
    start_date: date
    end_date: date


class AnalyzePosInput(BaseModel):
    analysis: Literal["product_mix", "observed_prices", "payment_modes", "time_of_day"]
    outlet_codes: list[str] = Field(default_factory=list, max_length=12)
    start_date: date
    end_date: date
    menu_item: str | None = None


class AnalyzeSuppliersInput(BaseModel):
    analysis: Literal["invoice", "spend", "cost_trend", "price_change", "reconciliation"]
    supplier_query: str | None = None
    invoice_number: str | None = None
    start_date: date | None = None
    end_date: date | None = None
    group_by: Literal["all", "supplier", "month", "supplier_month"] = "supplier"


class DataCoverageInput(BaseModel):
    area: Literal["all", "sales", "invoices", "wastage", "staffing"] = "all"


class KopiPriceChangeInput(BaseModel):
    menu_scope: Literal["base_kopi", "all_kopi"] = "base_kopi"
    start_date: date
    end_date: date
    gross_price_increase_sgd: Decimal = Field(default=Decimal("0.10"), gt=0, le=1)
    demand_change_percent: list[Decimal] = Field(
        default_factory=lambda: [Decimal("0"), Decimal("-5"), Decimal("-10")],
        min_length=1,
        max_length=10,
    )
    outlet_codes: list[str] = Field(default_factory=list, max_length=12)


@lru_cache(maxsize=1)
def _repository() -> MySQLRepository:
    return MySQLRepository()


def _call(method: str, *args: Any, **kwargs: Any) -> dict[str, Any]:
    try:
        result = getattr(_repository(), method)(*args, **kwargs)
        return {"ok": True, **result}
    except ValueError as error:
        return {"ok": False, "error": str(error), "error_type": "validation"}
    except pymysql.MySQLError:
        return {
            "ok": False,
            "error": "The database query failed. Check database availability and configuration.",
            "error_type": "database",
        }


@tool("analyze_outlets", args_schema=AnalyzeOutletsInput)
def analyze_outlets(
    analysis: str,
    start_date: date,
    end_date: date,
    outlet_codes: list[str] | None = None,
) -> dict[str, Any]:
    """Analyze authoritative outlet performance, measured wastage, or roster-based staffing."""
    return _call("analyze_outlets", analysis, outlet_codes or [], start_date, end_date)


@tool("analyze_pos", args_schema=AnalyzePosInput)
def analyze_pos(
    analysis: str, start_date: date, end_date: date,
    outlet_codes: list[str] | None = None, menu_item: str | None = None,
) -> dict[str, Any]:
    """Analyze product mix, observed prices, payments, or time patterns in the partial POS export."""
    return _call("analyze_pos", analysis, outlet_codes or [], start_date, end_date, menu_item)


@tool("analyze_suppliers", args_schema=AnalyzeSuppliersInput)
def analyze_suppliers(
    analysis: str, supplier_query: str | None = None, invoice_number: str | None = None,
    start_date: date | None = None, end_date: date | None = None,
    group_by: str = "supplier",
) -> dict[str, Any]:
    """Analyze authoritative scanned invoices, supplier spend, prices, and reconciliation."""
    return _call("analyze_suppliers", analysis, supplier_query, invoice_number, start_date, end_date, group_by)


@tool("get_data_coverage", args_schema=DataCoverageInput)
def get_data_coverage(area: str = "all") -> dict[str, Any]:
    """Report objective source coverage and known completeness limitations."""
    return _call("get_data_coverage", area)


@tool("assess_kopi_price_change", args_schema=KopiPriceChangeInput)
def assess_kopi_price_change(
    start_date: date, end_date: date, menu_scope: str = "base_kopi",
    gross_price_increase_sgd: Decimal = Decimal("0.10"),
    demand_change_percent: list[Decimal] | None = None,
    outlet_codes: list[str] | None = None,
) -> dict[str, Any]:
    """Run a transparent price scenario from observed partial-POS volumes without overstating certainty."""
    return _call(
        "assess_kopi_price_change", menu_scope, start_date, end_date,
        gross_price_increase_sgd,
        demand_change_percent or [Decimal("0"), Decimal("-5"), Decimal("-10")],
        outlet_codes or [],
    )


@tool("get_outlet_sales", args_schema=OutletSalesInput)
def get_outlet_sales(
    outlet_code: str, start_date: date, end_date: date, include_daily: bool = True
) -> dict[str, Any]:
    """Get deduplicated POS sales for one outlet and period, with canonical alias handling and citation."""
    return _call("get_outlet_sales", outlet_code, start_date, end_date, include_daily)


@tool("compare_outlets", args_schema=CompareOutletsInput)
def compare_outlets(
    outlet_codes: list[str], start_date: date, end_date: date
) -> dict[str, Any]:
    """Compare deduplicated sales, transaction counts, and activity across selected outlets."""
    return _call("compare_outlets", outlet_codes, start_date, end_date)


@tool("get_invoice", args_schema=InvoiceInput)
def get_invoice(invoice_number: str) -> dict[str, Any]:
    """Get one scanned supplier invoice, its item rows, review state, reconciliation, and citation."""
    return _call("get_invoice", invoice_number)


@tool("get_supplier_cost_trend", args_schema=SupplierTrendInput)
def get_supplier_cost_trend(
    supplier_name: str, start_date: date, end_date: date
) -> dict[str, Any]:
    """Get monthly scanned-invoice totals and item unit-price trends for a supplier."""
    return _call("get_supplier_cost_trend", supplier_name, start_date, end_date)


@tool("search_documents", args_schema=DocumentSearchInput)
def search_documents(
    query: str,
    limit: int = 5,
    outlet_code: str | None = None,
    supplier_name: str | None = None,
) -> dict[str, Any]:
    """Search citable email and WhatsApp chunks, optionally filtered by explicit entity mentions."""
    return _call("search_documents", query, limit, outlet_code, supplier_name)


@tool("get_data_quality_issues", args_schema=QualityIssuesInput)
def get_data_quality_issues(
    status: str = "OPEN",
    severity: str | None = None,
    rule_code: str | None = None,
    limit: int = 50,
) -> dict[str, Any]:
    """List citable data-quality issues by status, severity, and rule code."""
    return _call("get_data_quality_issues", status, severity, rule_code, limit)


ALL_TOOLS = [
    analyze_outlets,
    analyze_pos,
    analyze_suppliers,
    get_data_coverage,
    search_documents,
    assess_kopi_price_change,
    get_data_quality_issues,
]
