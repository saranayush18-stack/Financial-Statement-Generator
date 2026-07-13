"""
Core data models for the AI Financial Statement Generator (Schedule III Engine).

These are plain dataclasses with no external framework dependency so the
engine can be embedded in FastAPI, a CLI, a notebook, or a batch job without
changes.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from enum import Enum
from typing import Optional


class Nature(str, Enum):
    """Whether a ledger normally carries a debit or credit balance."""
    DEBIT = "DEBIT"
    CREDIT = "CREDIT"


class Statement(str, Enum):
    """Which primary statement a mapped head feeds into."""
    BALANCE_SHEET = "BALANCE_SHEET"
    PROFIT_AND_LOSS = "PROFIT_AND_LOSS"
    NOT_APPLICABLE = "NOT_APPLICABLE"  # e.g. suspense, needs resolution


class CurrentNonCurrent(str, Enum):
    CURRENT = "CURRENT"
    NON_CURRENT = "NON_CURRENT"
    NOT_APPLICABLE = "NOT_APPLICABLE"  # P&L items don't carry this split


@dataclass
class Company:
    name: str
    cin: Optional[str] = None
    pan: Optional[str] = None
    gstin: Optional[str] = None
    registered_office: Optional[str] = None
    financial_year_start: date = field(default_factory=lambda: date(date.today().year, 4, 1))
    financial_year_end: date = field(default_factory=lambda: date(date.today().year + 1, 3, 31))
    currency: str = "INR"
    rounding: str = "ACTUALS"  # ACTUALS | THOUSANDS | LAKHS | MILLIONS | CRORES
    auditor: Optional[str] = None
    directors: list[str] = field(default_factory=list)
    company_id: Optional[int] = None


@dataclass
class LedgerEntry:
    """One row from the uploaded Trial Balance, before mapping."""
    ledger_name: str
    opening_balance: float = 0.0
    debit: float = 0.0
    credit: float = 0.0
    previous_year_closing: Optional[float] = None
    source_row: Optional[int] = None

    @property
    def closing_balance(self) -> float:
        """
        Positive = net debit, Negative = net credit (signed convention).

        NOTE: In a standard Trial Balance export (Tally/Busy/Zoho/QuickBooks/
        SAP), the Debit and Credit columns already represent each ledger's
        CLOSING position for the period -- they are not a movement to be
        added on top of Opening Balance. Opening Balance is retained on this
        model purely as an informational/comparative figure (e.g. to display
        alongside the closing balance, or for roll-forward checks), and is
        deliberately NOT included in this calculation to avoid double-counting.
        """
        return round(self.debit - self.credit, 2)


@dataclass
class MappingEntry:
    """A ledger's confirmed (or suggested) mapping to Schedule III."""
    ledger_name: str
    major_head: str
    sub_head: str
    statement: Statement
    current_or_non_current: CurrentNonCurrent
    nature: Nature
    confidence: float = 1.0          # 1.0 = user-confirmed, <1.0 = auto-suggested
    source: str = "MANUAL"           # MANUAL | RULE_ENGINE | AI_SUGGESTED
    note_ref: Optional[str] = None   # which Note to Accounts this rolls into


@dataclass
class TrialBalance:
    company: Company
    financial_year_label: str  # e.g. "FY 2025-26"
    ledgers: list[LedgerEntry] = field(default_factory=list)

    def total_debit(self) -> float:
        return round(sum(l.debit for l in self.ledgers), 2)

    def total_credit(self) -> float:
        return round(sum(l.credit for l in self.ledgers), 2)

    def is_balanced(self, tolerance: float = 1.0) -> bool:
        return abs(self.total_debit() - self.total_credit()) <= tolerance


@dataclass
class ValidationIssue:
    severity: str      # ERROR | WARNING | INFO
    code: str
    ledger_name: Optional[str]
    message: str
    amount: Optional[float] = None
