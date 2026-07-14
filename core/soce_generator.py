"""
Statement of Changes in Equity (SOCE) Generator.

Schedule III to the Companies Act, 2013 requires an SOCE (Part A: Equity
Share Capital, Part B: Other Equity) as a primary statement for companies
following Ind AS (Division II), and it is increasingly presented as good
practice even for Division I (non-Ind AS) companies since it is the only
statement that shows the full roll-forward of each equity component. This
module builds it from what a Trial Balance can actually support: opening
balance (previous year closing), the current year's movement, and the
current year's profit (from the P&L).

Design choice: a plain Trial Balance has no transaction-level history for
equity (e.g. "which reserve did this year's dividend come out of"), so
this generator can only reconcile at the ledger level:
    Closing = Opening + Profit-for-the-year-transferred (if applicable)
              + Other movements during the year (residual plug)
"Other movements" is reported explicitly as its own row rather than
silently folded into "Profit for the year", so a reviewing partner can see
exactly which figure is a plug versus a source-verified number.

Reserve components are sub-classified into the standard Schedule III
categories (Capital Reserve, Securities Premium, General Reserve,
Statutory Reserve, Surplus in Statement of P&L) using the same transparent
keyword approach as the main classifier -- every bucket assignment is
traceable back to a keyword in the ledger name.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from core.statement_generator import BalanceSheet, ProfitAndLoss, LineItem

# Ordered: first keyword match wins. Ledgers not matching anything fall
# into "Surplus in Statement of Profit and Loss" (the standard catch-all
# for retained earnings / accumulated profit).
RESERVE_COMPONENT_KEYWORDS: list[tuple[str, list[str]]] = [
    ("Capital Reserve", ["capital reserve"]),
    ("Securities Premium", ["securities premium", "share premium"]),
    ("Statutory Reserve", ["statutory reserve"]),
    ("General Reserve", ["general reserve"]),
    ("Revaluation Reserve", ["revaluation reserve"]),
]
SURPLUS_BUCKET = "Surplus in Statement of Profit and Loss"


def _reserve_component(ledger_name: str) -> str:
    normalized = ledger_name.lower()
    for bucket, keywords in RESERVE_COMPONENT_KEYWORDS:
        if any(kw in normalized for kw in keywords):
            return bucket
    return SURPLUS_BUCKET


@dataclass
class EquityShareCapitalRoll:
    opening: float
    changes_during_year: float
    closing: float


@dataclass
class OtherEquityComponentRoll:
    component: str
    opening: float
    profit_for_the_year: float
    other_movements: float
    closing: float


@dataclass
class StatementOfChangesInEquity:
    equity_share_capital: EquityShareCapitalRoll
    other_equity: list[OtherEquityComponentRoll]
    total_other_equity_opening: float
    total_other_equity_closing: float


def _sub_head_ledgers(bs: BalanceSheet, sub_head_name: str) -> list[LineItem]:
    for section in (bs.equity_and_liabilities, bs.assets):
        for major in section:
            for sh in major.sub_heads:
                if sh.sub_head == sub_head_name:
                    return sh.ledgers
    return []


def generate_soce(bs: BalanceSheet, pnl: ProfitAndLoss) -> StatementOfChangesInEquity:
    # --- Part A: Equity Share Capital ---
    share_capital_ledgers = _sub_head_ledgers(bs, "Share Capital")
    sc_opening = round(sum(l.previous_year for l in share_capital_ledgers), 2)
    sc_closing = round(sum(l.current_year for l in share_capital_ledgers), 2)
    equity_share_capital = EquityShareCapitalRoll(
        opening=sc_opening,
        changes_during_year=round(sc_closing - sc_opening, 2),
        closing=sc_closing,
    )

    # --- Part B: Other Equity (Reserves and Surplus, broken into components) ---
    reserve_ledgers = _sub_head_ledgers(bs, "Reserves and Surplus")
    # Bucket by component, excluding the "Add: Profit for the Current Year"
    # line that carry_profit_into_reserves() appended -- that is handled
    # separately below as its own explicit SOCE row so it isn't
    # double-counted inside "other movements".
    buckets: dict[str, dict[str, float]] = {}
    profit_line_label_prefix = "Add: Profit for the Current Year"

    for ledger in reserve_ledgers:
        if ledger.label.startswith(profit_line_label_prefix):
            continue
        bucket = _reserve_component(ledger.label)
        b = buckets.setdefault(bucket, {"opening": 0.0, "closing": 0.0})
        b["opening"] = round(b["opening"] + ledger.previous_year, 2)
        b["closing"] = round(b["closing"] + ledger.current_year, 2)

    # Ensure the Surplus bucket exists even if every reserve ledger matched
    # a named component, since profit-for-the-year always lands there.
    buckets.setdefault(SURPLUS_BUCKET, {"opening": 0.0, "closing": 0.0})

    profit_cy = pnl.profit_after_tax_cy
    other_equity: list[OtherEquityComponentRoll] = []
    for component, vals in buckets.items():
        profit_for_year = profit_cy if component == SURPLUS_BUCKET else 0.0
        # vals["closing"] is the real Surplus ledger's own closing balance
        # BEFORE the current year's profit is added -- carry_profit_into_
        # reserves() stores that addition as a separate synthetic line
        # (skipped above), not inside the ledger itself. "Other movements"
        # is therefore simply the real ledger's own year-on-year movement
        # (transfers, dividends, prior period adjustments); the reported
        # closing balance must add the profit transfer back on top of it.
        other_movements = round(vals["closing"] - vals["opening"], 2)
        closing = round(vals["opening"] + profit_for_year + other_movements, 2)
        other_equity.append(OtherEquityComponentRoll(
            component=component,
            opening=vals["opening"],
            profit_for_the_year=profit_for_year,
            other_movements=other_movements,
            closing=closing,
        ))

    # Stable, statute-conventional ordering.
    order = ["Capital Reserve", "Securities Premium", "Statutory Reserve",
             "General Reserve", "Revaluation Reserve", SURPLUS_BUCKET]
    other_equity.sort(key=lambda r: order.index(r.component) if r.component in order else 99)

    total_opening = round(sum(r.opening for r in other_equity), 2)
    total_closing = round(sum(r.closing for r in other_equity), 2)

    return StatementOfChangesInEquity(
        equity_share_capital=equity_share_capital,
        other_equity=other_equity,
        total_other_equity_opening=total_opening,
        total_other_equity_closing=total_closing,
    )


def soce_reconciles_to_balance_sheet(soce: StatementOfChangesInEquity, bs: BalanceSheet, tolerance: float = 1.0) -> bool:
    """Cross-check that SOCE's closing figures agree with the Balance
    Sheet's Share Capital and Reserves and Surplus sub-heads -- they are
    two views of the same ledgers and must never diverge."""
    bs_share_capital = sum(l.current_year for l in _sub_head_ledgers(bs, "Share Capital"))
    bs_reserves = sum(l.current_year for l in _sub_head_ledgers(bs, "Reserves and Surplus"))
    sc_ok = abs(soce.equity_share_capital.closing - bs_share_capital) <= tolerance
    oe_ok = abs(soce.total_other_equity_closing - bs_reserves) <= tolerance
    return sc_ok and oe_ok
