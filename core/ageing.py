"""
Trade Receivables / Trade Payables Ageing Schedule.

Mandatory under Schedule III (amended 2021) for every company, split into
the statutory bucket structure:
    Not Due | Less than 6 months | 6 months - 1 year | 1-2 years |
    2-3 years | More than 3 years
and, within that, split by:
    Undisputed - Considered Good | Undisputed - Considered Doubtful |
    Disputed - Considered Good  | Disputed - Considered Doubtful

CRITICAL DATA LIMITATION: a Trial Balance has one closing figure per
ledger -- it has no party-wise, invoice-wise, or due-date-wise detail.
Ageing genuinely cannot be computed from a TB alone; it requires a
supplementary party ledger / debtors-creditors listing with due dates.
This module therefore does two things:

1. If the caller supplies that supplementary data (via `parse_ageing_file`
   or a list of `AgeingLineItem`), it computes the real statutory grid and
   cross-checks the grid total against the Balance Sheet's Trade
   Receivables / Trade Payables figure.
2. If no supplementary data is supplied, it returns an explicit
   "not available" result rather than fabricating buckets -- silently
   putting everything in one bucket would be a materially misleading
   disclosure, worse than admitting the data gap.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Optional

import pandas as pd

from models import ValidationIssue

BUCKET_LABELS = [
    "Not Due",
    "Less than 6 months",
    "6 months - 1 year",
    "1-2 years",
    "2-3 years",
    "More than 3 years",
]

CATEGORY_LABELS = [
    "Undisputed - Considered Good",
    "Undisputed - Considered Doubtful",
    "Disputed - Considered Good",
    "Disputed - Considered Doubtful",
]


@dataclass
class AgeingLineItem:
    party_name: str
    amount: float
    due_date: date
    disputed: bool = False
    considered_doubtful: bool = False


@dataclass
class AgeingGrid:
    ledger_type: str  # "Trade Receivables" | "Trade Payables"
    as_of: date
    available: bool
    grid: dict[str, dict[str, float]] = field(default_factory=dict)  # category -> bucket -> amount
    total: float = 0.0
    reconciles_to_balance_sheet: Optional[bool] = None
    balance_sheet_amount: Optional[float] = None
    unavailable_reason: Optional[str] = None


def _bucket_for(due_date: date, as_of: date) -> str:
    days_overdue = (as_of - due_date).days
    if days_overdue < 0:
        return "Not Due"
    if days_overdue <= 182:
        return "Less than 6 months"
    if days_overdue <= 365:
        return "6 months - 1 year"
    if days_overdue <= 730:
        return "1-2 years"
    if days_overdue <= 1095:
        return "2-3 years"
    return "More than 3 years"


def _category_for(item: AgeingLineItem) -> str:
    if item.disputed and item.considered_doubtful:
        return "Disputed - Considered Doubtful"
    if item.disputed:
        return "Disputed - Considered Good"
    if item.considered_doubtful:
        return "Undisputed - Considered Doubtful"
    return "Undisputed - Considered Good"


def build_ageing_grid(
    ledger_type: str,
    items: list[AgeingLineItem],
    as_of: date,
    balance_sheet_amount: Optional[float] = None,
    tolerance: float = 1.0,
) -> AgeingGrid:
    grid: dict[str, dict[str, float]] = {
        cat: {bucket: 0.0 for bucket in BUCKET_LABELS} for cat in CATEGORY_LABELS
    }
    for item in items:
        cat = _category_for(item)
        bucket = _bucket_for(item.due_date, as_of)
        grid[cat][bucket] = round(grid[cat][bucket] + item.amount, 2)

    total = round(sum(sum(row.values()) for row in grid.values()), 2)

    reconciles = None
    if balance_sheet_amount is not None:
        reconciles = abs(total - balance_sheet_amount) <= tolerance

    return AgeingGrid(
        ledger_type=ledger_type, as_of=as_of, available=True, grid=grid, total=total,
        reconciles_to_balance_sheet=reconciles, balance_sheet_amount=balance_sheet_amount,
    )


def unavailable_grid(ledger_type: str, as_of: date, reason: str) -> AgeingGrid:
    return AgeingGrid(
        ledger_type=ledger_type, as_of=as_of, available=False,
        unavailable_reason=reason,
    )


def ageing_validation_issues(grid: AgeingGrid) -> list[ValidationIssue]:
    """Surfaces the ageing grid's state into the same Validation Engine
    report the rest of the pipeline uses, so a reviewing partner sees it
    alongside every other open item rather than having to check a
    separate sheet."""
    issues: list[ValidationIssue] = []
    if not grid.available:
        issues.append(ValidationIssue(
            severity="INFO", code="AGEING_NOT_AVAILABLE", ledger_name=None,
            message=(
                f"{grid.ledger_type} ageing schedule not prepared: {grid.unavailable_reason} "
                "This is a mandatory Schedule III disclosure and must be completed before "
                "the financial statements are finalized."
            ),
        ))
    elif grid.reconciles_to_balance_sheet is False:
        issues.append(ValidationIssue(
            severity="ERROR", code="AGEING_MISMATCH", ledger_name=None,
            message=(
                f"{grid.ledger_type} ageing schedule total ({grid.total:,.2f}) does not "
                f"reconcile to the Balance Sheet figure ({grid.balance_sheet_amount:,.2f})."
            ),
            amount=round(grid.total - (grid.balance_sheet_amount or 0.0), 2),
        ))
    return issues


# ---------------------------------------------------------------------------
# Optional supplementary file parser
# ---------------------------------------------------------------------------
# Expected columns (case/spacing-insensitive, aliases supported):
#   Party Name, Amount, Due Date, Disputed (Y/N, optional), Doubtful (Y/N, optional)

_COLUMN_ALIASES = {
    "party_name": ["party name", "party", "customer name", "vendor name", "name"],
    "amount": ["amount", "outstanding amount", "balance", "outstanding"],
    "due_date": ["due date", "invoice due date", "due"],
    "disputed": ["disputed", "dispute"],
    "doubtful": ["doubtful", "considered doubtful", "provision"],
}


def _find_col(columns: list[str], aliases: list[str]) -> Optional[str]:
    cleaned = {c: str(c).strip().lower() for c in columns}
    for col, clean in cleaned.items():
        if clean in aliases:
            return col
    for col, clean in cleaned.items():
        if any(a in clean for a in aliases):
            return col
    return None


def _to_bool(val) -> bool:
    if pd.isna(val):
        return False
    return str(val).strip().lower() in ("y", "yes", "true", "1")


def parse_ageing_file(path: str | Path) -> list[AgeingLineItem]:
    """Reads an optional party-wise ledger/ageing input file (xlsx or csv).
    Raises ValueError with a clear message if required columns are missing
    -- this surfaces to the user as an actionable error, not a silent
    fallback to fabricated buckets."""
    path = Path(path)
    if path.suffix.lower() == ".csv":
        df = pd.read_csv(path)
    else:
        df = pd.read_excel(path)

    columns = list(df.columns)
    party_col = _find_col(columns, _COLUMN_ALIASES["party_name"])
    amount_col = _find_col(columns, _COLUMN_ALIASES["amount"])
    due_date_col = _find_col(columns, _COLUMN_ALIASES["due_date"])
    disputed_col = _find_col(columns, _COLUMN_ALIASES["disputed"])
    doubtful_col = _find_col(columns, _COLUMN_ALIASES["doubtful"])

    missing = [name for name, col in [("Party Name", party_col), ("Amount", amount_col),
                                       ("Due Date", due_date_col)] if col is None]
    if missing:
        raise ValueError(
            f"Ageing file is missing required column(s): {', '.join(missing)}. "
            "Expected at minimum: Party Name, Amount, Due Date."
        )

    items: list[AgeingLineItem] = []
    for _, row in df.iterrows():
        if pd.isna(row[party_col]) and pd.isna(row[amount_col]):
            continue
        due_date_val = pd.to_datetime(row[due_date_col]).date()
        items.append(AgeingLineItem(
            party_name=str(row[party_col]),
            amount=round(float(row[amount_col]), 2),
            due_date=due_date_val,
            disputed=_to_bool(row[disputed_col]) if disputed_col else False,
            considered_doubtful=_to_bool(row[doubtful_col]) if doubtful_col else False,
        ))
    return items
