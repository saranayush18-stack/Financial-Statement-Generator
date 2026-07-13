"""
Financial Ratio computation from generated statements.
"""
from __future__ import annotations

from dataclasses import dataclass

from schedule3_engine.core.statement_generator import BalanceSheet, ProfitAndLoss


def _safe_div(numerator: float, denominator: float) -> float | None:
    if not denominator:
        return None
    return round(numerator / denominator, 2)


@dataclass
class RatioResult:
    name: str
    current_year: float | None
    previous_year: float | None
    formula: str


def _sub_head_value(bs: BalanceSheet, name: str, py: bool = False) -> float:
    for section in (bs.equity_and_liabilities, bs.assets):
        for major in section:
            for sh in major.sub_heads:
                if sh.sub_head == name:
                    return sh.previous_year if py else sh.current_year
    return 0.0


def compute_ratios(bs: BalanceSheet, pnl: ProfitAndLoss) -> list[RatioResult]:
    current_assets_heads = ["Current Investments", "Inventories", "Trade Receivables",
                             "Cash and Cash Equivalents", "Short-Term Loans and Advances",
                             "Other Current Assets"]
    current_liab_heads = ["Short-Term Borrowings", "Trade Payables",
                           "Other Current Liabilities", "Short-Term Provisions"]

    def total(heads, py=False):
        return round(sum(_sub_head_value(bs, h, py) for h in heads), 2)

    ca_cy, ca_py = total(current_assets_heads), total(current_assets_heads, True)
    cl_cy, cl_py = total(current_liab_heads), total(current_liab_heads, True)
    inventory_cy, inventory_py = _sub_head_value(bs, "Inventories"), _sub_head_value(bs, "Inventories", True)
    receivables_cy = _sub_head_value(bs, "Trade Receivables")
    receivables_py = _sub_head_value(bs, "Trade Receivables", True)
    payables_cy = _sub_head_value(bs, "Trade Payables")
    payables_py = _sub_head_value(bs, "Trade Payables", True)

    share_capital_cy = _sub_head_value(bs, "Share Capital")
    share_capital_py = _sub_head_value(bs, "Share Capital", True)
    reserves_cy = _sub_head_value(bs, "Reserves and Surplus")
    reserves_py = _sub_head_value(bs, "Reserves and Surplus", True)
    equity_cy = round(share_capital_cy + reserves_cy, 2)
    equity_py = round(share_capital_py + reserves_py, 2)

    ltb_cy = _sub_head_value(bs, "Long-Term Borrowings")
    ltb_py = _sub_head_value(bs, "Long-Term Borrowings", True)
    stb_cy = _sub_head_value(bs, "Short-Term Borrowings")
    stb_py = _sub_head_value(bs, "Short-Term Borrowings", True)
    total_debt_cy = round(ltb_cy + stb_cy, 2)
    total_debt_py = round(ltb_py + stb_py, 2)

    revenue_cy, revenue_py = pnl.total_revenue_cy, pnl.total_revenue_py
    pat_cy, pat_py = pnl.profit_after_tax_cy, pnl.profit_after_tax_py

    capital_employed_cy = round(equity_cy + ltb_cy, 2)
    capital_employed_py = round(equity_py + ltb_py, 2)
    ebit_cy = round(pnl.profit_before_tax_cy + sum(
        e.current_year for e in pnl.expenses if e.sub_head == "Finance Costs"), 2)
    ebit_py = round(pnl.profit_before_tax_py + sum(
        e.previous_year for e in pnl.expenses if e.sub_head == "Finance Costs"), 2)

    gross_profit_cy = round(revenue_cy - sum(
        e.current_year for e in pnl.expenses
        if e.sub_head in ("Cost of Materials Consumed", "Purchases of Stock-in-Trade",
                           "Changes in Inventories of Finished Goods, WIP and Stock-in-Trade")
    ), 2)
    gross_profit_py = round(revenue_py - sum(
        e.previous_year for e in pnl.expenses
        if e.sub_head in ("Cost of Materials Consumed", "Purchases of Stock-in-Trade",
                           "Changes in Inventories of Finished Goods, WIP and Stock-in-Trade")
    ), 2)

    results = [
        RatioResult("Current Ratio", _safe_div(ca_cy, cl_cy), _safe_div(ca_py, cl_py),
                    "Current Assets / Current Liabilities"),
        RatioResult("Quick Ratio", _safe_div(ca_cy - inventory_cy, cl_cy),
                    _safe_div(ca_py - inventory_py, cl_py),
                    "(Current Assets - Inventory) / Current Liabilities"),
        RatioResult("Debt-Equity Ratio", _safe_div(total_debt_cy, equity_cy),
                    _safe_div(total_debt_py, equity_py), "Total Debt / Shareholders' Equity"),
        RatioResult("Return on Equity (%)",
                    _safe_div(pat_cy * 100, equity_cy), _safe_div(pat_py * 100, equity_py),
                    "Profit After Tax / Shareholders' Equity x 100"),
        RatioResult("Return on Capital Employed (%)",
                    _safe_div(ebit_cy * 100, capital_employed_cy),
                    _safe_div(ebit_py * 100, capital_employed_py),
                    "EBIT / Capital Employed x 100"),
        RatioResult("Gross Profit Margin (%)", _safe_div(gross_profit_cy * 100, revenue_cy),
                    _safe_div(gross_profit_py * 100, revenue_py),
                    "Gross Profit / Revenue x 100"),
        RatioResult("Net Profit Margin (%)", _safe_div(pat_cy * 100, revenue_cy),
                    _safe_div(pat_py * 100, revenue_py), "Profit After Tax / Revenue x 100"),
        RatioResult("Inventory Turnover Ratio",
                    _safe_div(revenue_cy - gross_profit_cy, inventory_cy),
                    _safe_div(revenue_py - gross_profit_py, inventory_py),
                    "Cost of Goods Sold / Average Inventory"),
        RatioResult("Trade Receivables Turnover Ratio", _safe_div(revenue_cy, receivables_cy),
                    _safe_div(revenue_py, receivables_py), "Revenue / Average Trade Receivables"),
        RatioResult("Trade Payables Turnover Ratio",
                    _safe_div(revenue_cy - gross_profit_cy, payables_cy),
                    _safe_div(revenue_py - gross_profit_py, payables_py),
                    "Purchases / Average Trade Payables"),
        RatioResult("Book Value per Share", None, None,
                    "Shareholders' Equity / Number of Equity Shares (requires share count input)"),
        RatioResult("Earnings per Share", None, None,
                    "Profit After Tax / Weighted Avg. Number of Equity Shares (requires share count input)"),
    ]
    return results
