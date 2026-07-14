"""
Statement Generator.

Takes a Trial Balance + resolved mappings and produces the Schedule III
primary statements as structured Python objects (not yet formatted for
Excel/PDF -- that's export/excel_export.py and export/pdf_export.py).

Sign convention used throughout this module:
- LedgerEntry.closing_balance is signed: positive = net debit, negative = net credit.
- For BALANCE SHEET credit-nature heads (liabilities & equity), we report the
  natural positive amount as -closing_balance (so a normal credit ledger shows
  as a positive liability figure).
- For debit-nature heads (assets), we report +closing_balance directly.
- For P&L, revenue (credit nature) is reported as -closing_balance (positive
  income), and expenses (debit nature) as +closing_balance (positive expense).
"""
from __future__ import annotations

from dataclasses import dataclass, field

from models import TrialBalance, MappingEntry, Statement, CurrentNonCurrent, Nature
from data.classification_rules import SCHEDULE_III_STRUCTURE


@dataclass
class LineItem:
    label: str
    current_year: float
    previous_year: float = 0.0
    note_ref: str | None = None


@dataclass
class SubHeadTotal:
    sub_head: str
    current_year: float
    previous_year: float
    note_ref: str | None
    ledgers: list[LineItem] = field(default_factory=list)


@dataclass
class MajorHeadTotal:
    major_head: str
    current_year: float
    previous_year: float
    sub_heads: list[SubHeadTotal] = field(default_factory=list)


@dataclass
class BalanceSheet:
    equity_and_liabilities: list[MajorHeadTotal]
    assets: list[MajorHeadTotal]
    total_equity_and_liabilities_cy: float
    total_equity_and_liabilities_py: float
    total_assets_cy: float
    total_assets_py: float

    @property
    def is_tallied(self) -> bool:
        return abs(self.total_equity_and_liabilities_cy - self.total_assets_cy) < 1


@dataclass
class ProfitAndLoss:
    revenue: list[SubHeadTotal]
    expenses: list[SubHeadTotal]
    total_revenue_cy: float
    total_revenue_py: float
    total_expenses_cy: float
    total_expenses_py: float
    tax_expense_cy: float
    tax_expense_py: float

    @property
    def profit_before_tax_cy(self) -> float:
        return round(self.total_revenue_cy - self.total_expenses_cy, 2)

    @property
    def profit_before_tax_py(self) -> float:
        return round(self.total_revenue_py - self.total_expenses_py, 2)

    @property
    def profit_after_tax_cy(self) -> float:
        return round(self.profit_before_tax_cy - self.tax_expense_cy, 2)

    @property
    def profit_after_tax_py(self) -> float:
        return round(self.profit_before_tax_py - self.tax_expense_py, 2)


@dataclass
class CashFlowStatement:
    """Indirect method. PY figures are optional (need two years of TBs)."""
    net_profit_before_tax: float
    depreciation_addback: float
    interest_expense_addback: float
    working_capital_changes: dict[str, float]
    cash_from_operations: float
    cash_from_investing: float
    cash_from_financing: float
    net_increase_in_cash: float
    opening_cash: float
    closing_cash: float


def _group_by_sub_head(
    tb: TrialBalance, mappings: dict[str, MappingEntry], target_statement: Statement
) -> dict[str, SubHeadTotal]:
    result: dict[str, SubHeadTotal] = {}
    by_ledger = {l.ledger_name: l for l in tb.ledgers}

    for ledger_name, mapping in mappings.items():
        if mapping.statement != target_statement:
            continue
        ledger = by_ledger.get(ledger_name)
        if ledger is None:
            continue

        closing = ledger.closing_balance
        # apply sign convention based on nature
        signed_amount = closing if mapping.nature == Nature.DEBIT else -closing
        # Previous Year Closing is captured as an UNSIGNED magnitude (see
        # tb_parser.py / sample data) -- it already represents the correct
        # natural-positive figure for the ledger's nature (e.g. a positive
        # number for a normal liability balance), unlike closing_balance
        # which is a signed debit-minus-credit figure. It must NOT be
        # sign-flipped again here, or every credit-nature previous-year
        # figure (liabilities, equity, revenue) comes out negative.
        py = ledger.previous_year_closing
        py_signed = py if py is not None else 0.0

        key = mapping.sub_head
        if key not in result:
            result[key] = SubHeadTotal(
                sub_head=key, current_year=0.0, previous_year=0.0,
                note_ref=mapping.note_ref, ledgers=[],
            )
        result[key].current_year = round(result[key].current_year + signed_amount, 2)
        result[key].previous_year = round(result[key].previous_year + py_signed, 2)
        result[key].ledgers.append(
            LineItem(label=ledger_name, current_year=round(signed_amount, 2),
                      previous_year=round(py_signed, 2), note_ref=mapping.note_ref)
        )

    return result


def generate_balance_sheet(tb: TrialBalance, mappings: dict[str, MappingEntry]) -> BalanceSheet:
    sub_head_totals = _group_by_sub_head(tb, mappings, Statement.BALANCE_SHEET)
    structure = SCHEDULE_III_STRUCTURE["BALANCE_SHEET"]

    def build_section(section_name: str) -> list[MajorHeadTotal]:
        majors: list[MajorHeadTotal] = []
        for major_head, sub_heads in structure[section_name].items():
            sub_totals = [sub_head_totals[sh] for sh in sub_heads if sh in sub_head_totals]
            cy = round(sum(s.current_year for s in sub_totals), 2)
            py = round(sum(s.previous_year for s in sub_totals), 2)
            if sub_totals:
                majors.append(MajorHeadTotal(major_head=major_head, current_year=cy,
                                              previous_year=py, sub_heads=sub_totals))
        return majors

    equity_and_liabilities = build_section("EQUITY AND LIABILITIES")
    assets = build_section("ASSETS")

    total_el_cy = round(sum(m.current_year for m in equity_and_liabilities), 2)
    total_el_py = round(sum(m.previous_year for m in equity_and_liabilities), 2)
    total_assets_cy = round(sum(m.current_year for m in assets), 2)
    total_assets_py = round(sum(m.previous_year for m in assets), 2)

    return BalanceSheet(
        equity_and_liabilities=equity_and_liabilities,
        assets=assets,
        total_equity_and_liabilities_cy=total_el_cy,
        total_equity_and_liabilities_py=total_el_py,
        total_assets_cy=total_assets_cy,
        total_assets_py=total_assets_py,
    )


def carry_profit_into_reserves(bs: BalanceSheet, pnl: ProfitAndLoss) -> BalanceSheet:
    """
    Schedule III presentation requires the current year's Profit for the
    Period (from the P&L) to be carried into "Reserves and Surplus" under
    Shareholders' Funds on the Balance Sheet -- revenue/expense ledgers in
    the Trial Balance are not yet closed into a balance sheet account, so
    without this step the Balance Sheet will never tally even though the
    underlying Trial Balance is perfectly balanced (Total Debit = Total
    Credit). This mirrors how every real Schedule III working paper adds a
    "Add: Profit for the year" line into Reserves and Surplus.
    """
    profit_cy = pnl.profit_after_tax_cy
    profit_py = pnl.profit_after_tax_py
    found = False

    for major in bs.equity_and_liabilities:
        if major.major_head != "Shareholders' Funds":
            continue
        for sh in major.sub_heads:
            if sh.sub_head == "Reserves and Surplus":
                sh.ledgers.append(LineItem(
                    label="Add: Profit for the Current Year (transferred from Statement of Profit and Loss)",
                    current_year=profit_cy, previous_year=profit_py,
                    note_ref=sh.note_ref,
                ))
                sh.current_year = round(sh.current_year + profit_cy, 2)
                sh.previous_year = round(sh.previous_year + profit_py, 2)
                found = True
        if found:
            major.current_year = round(sum(s.current_year for s in major.sub_heads), 2)
            major.previous_year = round(sum(s.previous_year for s in major.sub_heads), 2)

    if not found:
        # No "Reserves and Surplus" ledger existed at all (e.g. first year of
        # incorporation) -- create the sub-head so the profit still has a home.
        new_sub = SubHeadTotal(
            sub_head="Reserves and Surplus", current_year=profit_cy, previous_year=profit_py,
            note_ref="Note 2 - Reserves and Surplus",
            ledgers=[LineItem(label="Profit for the Current Year", current_year=profit_cy,
                               previous_year=profit_py, note_ref="Note 2 - Reserves and Surplus")],
        )
        for major in bs.equity_and_liabilities:
            if major.major_head == "Shareholders' Funds":
                major.sub_heads.append(new_sub)
                major.current_year = round(major.current_year + profit_cy, 2)
                major.previous_year = round(major.previous_year + profit_py, 2)
                found = True
        if not found:
            new_major = MajorHeadTotal(major_head="Shareholders' Funds", current_year=profit_cy,
                                        previous_year=profit_py, sub_heads=[new_sub])
            bs.equity_and_liabilities.insert(0, new_major)

    bs.total_equity_and_liabilities_cy = round(
        sum(m.current_year for m in bs.equity_and_liabilities), 2)
    bs.total_equity_and_liabilities_py = round(
        sum(m.previous_year for m in bs.equity_and_liabilities), 2)
    return bs


def generate_profit_and_loss(tb: TrialBalance, mappings: dict[str, MappingEntry]) -> ProfitAndLoss:
    sub_head_totals = _group_by_sub_head(tb, mappings, Statement.PROFIT_AND_LOSS)
    structure = SCHEDULE_III_STRUCTURE["PROFIT_AND_LOSS"]

    revenue = [sub_head_totals[sh] for sh in structure["Revenue"] if sh in sub_head_totals]
    expenses = [sub_head_totals[sh] for sh in structure["Expenses"] if sh in sub_head_totals]
    tax = [sub_head_totals[sh] for sh in structure["Tax"] if sh in sub_head_totals]

    total_revenue_cy = round(sum(r.current_year for r in revenue), 2)
    total_revenue_py = round(sum(r.previous_year for r in revenue), 2)
    total_expenses_cy = round(sum(e.current_year for e in expenses), 2)
    total_expenses_py = round(sum(e.previous_year for e in expenses), 2)
    tax_cy = round(sum(t.current_year for t in tax), 2)
    tax_py = round(sum(t.previous_year for t in tax), 2)

    return ProfitAndLoss(
        revenue=revenue, expenses=expenses,
        total_revenue_cy=total_revenue_cy, total_revenue_py=total_revenue_py,
        total_expenses_cy=total_expenses_cy, total_expenses_py=total_expenses_py,
        tax_expense_cy=tax_cy, tax_expense_py=tax_py,
    )


def generate_cash_flow_indirect(
    tb: TrialBalance,
    mappings: dict[str, MappingEntry],
    pnl: ProfitAndLoss,
    bs: BalanceSheet,
) -> CashFlowStatement:
    """
    Simplified indirect-method cash flow. Requires previous_year_closing to be
    populated on ledgers for a meaningful working-capital movement; if absent,
    movements are reported as 0 with a caller-visible caveat (see notes below).
    """
    def sub_head_lookup(section: list[MajorHeadTotal], name: str) -> SubHeadTotal | None:
        for major in section:
            for sh in major.sub_heads:
                if sh.sub_head == name:
                    return sh
        return None

    depreciation = 0.0
    for e in pnl.expenses:
        if e.sub_head == "Depreciation and Amortization Expense":
            depreciation = e.current_year
    interest = 0.0
    for e in pnl.expenses:
        if e.sub_head == "Finance Costs":
            interest = e.current_year

    wc_items = ["Trade Receivables", "Inventories", "Short-Term Loans and Advances",
                "Other Current Assets", "Trade Payables", "Other Current Liabilities",
                "Short-Term Provisions"]
    working_capital_changes: dict[str, float] = {}
    for item in wc_items:
        sh = sub_head_lookup(bs.equity_and_liabilities, item) or sub_head_lookup(bs.assets, item)
        if sh:
            movement = round(sh.previous_year - sh.current_year, 2) if item in (
                "Trade Receivables", "Inventories", "Short-Term Loans and Advances",
                "Other Current Assets"
            ) else round(sh.current_year - sh.previous_year, 2)
            working_capital_changes[item] = movement

    cash_from_operations = round(
        pnl.profit_before_tax_cy + depreciation + interest + sum(working_capital_changes.values())
        - pnl.tax_expense_cy, 2
    )

    ppe_sh = sub_head_lookup(bs.assets, "Property, Plant and Equipment")
    cash_from_investing = round(-((ppe_sh.current_year - ppe_sh.previous_year) if ppe_sh else 0), 2)

    borrowings_sh = sub_head_lookup(bs.equity_and_liabilities, "Long-Term Borrowings")
    share_cap_sh = sub_head_lookup(bs.equity_and_liabilities, "Share Capital")
    cash_from_financing = round(
        ((borrowings_sh.current_year - borrowings_sh.previous_year) if borrowings_sh else 0)
        + ((share_cap_sh.current_year - share_cap_sh.previous_year) if share_cap_sh else 0)
        - interest, 2
    )

    net_increase = round(cash_from_operations + cash_from_investing + cash_from_financing, 2)

    cash_sh = sub_head_lookup(bs.assets, "Cash and Cash Equivalents")
    closing_cash = cash_sh.current_year if cash_sh else 0.0
    opening_cash = cash_sh.previous_year if cash_sh else 0.0

    return CashFlowStatement(
        net_profit_before_tax=pnl.profit_before_tax_cy,
        depreciation_addback=depreciation,
        interest_expense_addback=interest,
        working_capital_changes=working_capital_changes,
        cash_from_operations=cash_from_operations,
        cash_from_investing=cash_from_investing,
        cash_from_financing=cash_from_financing,
        net_increase_in_cash=net_increase,
        opening_cash=opening_cash,
        closing_cash=closing_cash,
    )
