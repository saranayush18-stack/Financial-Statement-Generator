"""
Trial Balance parser.

Accepts .xlsx / .xls / .csv exports from Tally, Busy, Zoho Books, QuickBooks,
or a plain manual Excel. Column names vary wildly across these systems, so
this module auto-detects the most likely column for ledger name / opening
balance / debit / credit / previous year closing using fuzzy header matching,
and falls back to positional guesses if headers are missing or generic
("Unnamed: 0" etc., which pandas produces for blank header cells).
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Optional

import pandas as pd

from models import LedgerEntry, TrialBalance, Company

# Header aliases seen across Tally / Busy / Zoho / QuickBooks / SAP exports.
HEADER_ALIASES = {
    "ledger_name": [
        "ledger name", "ledger", "account name", "account", "particulars",
        "name of account", "gl name", "gl account", "description",
    ],
    "opening_balance": [
        "opening balance", "op balance", "opening bal", "ob"
    ],
    "debit": [
        "debit", "dr", "debit amount", "debit amt", "dr amount",
    ],
    "credit": [
        "credit", "cr", "credit amount", "credit amt", "cr amount",
    ],
    "closing_balance": [
        "closing balance", "closing bal", "balance", "net balance", "cb"
    ],
    "previous_year": [
        "previous year", "py balance", "last year", "py closing",
        "previous year closing", "comparative"
    ],
}


def _clean_header(h) -> str:
    return re.sub(r"\s+", " ", str(h).strip().lower())


def _find_column(columns: list[str], candidates: list[str]) -> Optional[str]:
    cleaned = {c: _clean_header(c) for c in columns}
    for col, clean in cleaned.items():
        if clean in candidates:
            return col
    # partial/substring match as a fallback
    for col, clean in cleaned.items():
        for cand in candidates:
            if cand in clean:
                return col
    return None


def _to_number(val) -> float:
    if val is None or (isinstance(val, float) and pd.isna(val)):
        return 0.0
    if isinstance(val, (int, float)):
        return float(val)
    s = str(val).strip()
    if s == "" or s == "-":
        return 0.0
    negative = False
    if s.startswith("(") and s.endswith(")"):
        negative = True
        s = s[1:-1]
    s = s.replace(",", "").replace("₹", "").replace("Dr", "").replace("Cr", "").strip()
    try:
        num = float(s)
    except ValueError:
        return 0.0
    return -num if negative else num


class TrialBalanceParseError(Exception):
    pass


def parse_trial_balance(
    file_path: str,
    company: Company,
    financial_year_label: str,
    sheet_name: Optional[str] = None,
) -> tuple[TrialBalance, list[str]]:
    """
    Parse an uploaded Trial Balance file into a TrialBalance object.

    Returns (trial_balance, warnings). Raises TrialBalanceParseError if the
    file cannot be read at all or no ledger-name column can be identified.
    """
    warnings: list[str] = []
    path = Path(file_path)
    if not path.exists():
        raise TrialBalanceParseError(f"File not found: {file_path}")

    if path.suffix.lower() == ".csv":
        df = pd.read_csv(path)
    else:
        try:
            df = pd.read_excel(path, sheet_name=sheet_name or 0)
        except Exception as exc:
            raise TrialBalanceParseError(f"Could not read Excel file: {exc}") from exc

    if df.empty:
        raise TrialBalanceParseError("The uploaded file has no data rows.")

    # Drop fully-blank rows/columns (common in Tally exports with spacer rows)
    df = df.dropna(how="all").dropna(axis=1, how="all")
    columns = [str(c) for c in df.columns]

    col_ledger = _find_column(columns, HEADER_ALIASES["ledger_name"])
    col_opening = _find_column(columns, HEADER_ALIASES["opening_balance"])
    col_debit = _find_column(columns, HEADER_ALIASES["debit"])
    col_credit = _find_column(columns, HEADER_ALIASES["credit"])
    col_closing = _find_column(columns, HEADER_ALIASES["closing_balance"])
    col_py = _find_column(columns, HEADER_ALIASES["previous_year"])

    if col_ledger is None:
        # Fallback: assume first text-heavy column is the ledger name
        for c in columns:
            if df[c].dtype == object:
                col_ledger = c
                warnings.append(
                    f"No column header matched 'Ledger Name'; guessed column '{c}' "
                    "based on content. Please verify."
                )
                break
    if col_ledger is None:
        raise TrialBalanceParseError(
            "Could not identify a Ledger Name column. Please ensure the file "
            "has a column like 'Ledger Name', 'Particulars', or 'Account Name'."
        )

    if col_debit is None and col_credit is None and col_closing is None:
        raise TrialBalanceParseError(
            "Could not identify Debit/Credit or Closing Balance columns. "
            "Expected at least one of: Debit, Credit, Closing Balance."
        )

    ledgers: list[LedgerEntry] = []
    for idx, row in df.iterrows():
        name = row.get(col_ledger)
        if name is None or str(name).strip() == "" or str(name).strip().lower() == "nan":
            continue
        name = str(name).strip()
        # Skip obvious total/grand-total rows
        if name.lower() in {"total", "grand total", "total:", "grand total:"}:
            continue

        opening = _to_number(row.get(col_opening)) if col_opening else 0.0
        debit = _to_number(row.get(col_debit)) if col_debit else 0.0
        credit = _to_number(row.get(col_credit)) if col_credit else 0.0
        py = _to_number(row.get(col_py)) if col_py else None

        # If only a signed "closing balance" column exists (no separate Dr/Cr),
        # split it into debit/credit so downstream logic stays uniform.
        if col_debit is None and col_credit is None and col_closing:
            closing_val = _to_number(row.get(col_closing))
            if closing_val >= 0:
                debit, credit = closing_val, 0.0
            else:
                debit, credit = 0.0, abs(closing_val)

        ledgers.append(
            LedgerEntry(
                ledger_name=name,
                opening_balance=opening,
                debit=debit,
                credit=credit,
                previous_year_closing=py,
                source_row=int(idx) + 2,  # +2 approximates the Excel row number (header + 1-index)
            )
        )

    if not ledgers:
        raise TrialBalanceParseError("No valid ledger rows were found after parsing.")

    tb = TrialBalance(company=company, financial_year_label=financial_year_label, ledgers=ledgers)

    if not tb.is_balanced(tolerance=1.0):
        diff = round(tb.total_debit() - tb.total_credit(), 2)
        warnings.append(
            f"Trial Balance does not tie out: Total Debit {tb.total_debit():,.2f} vs "
            f"Total Credit {tb.total_credit():,.2f} (difference {diff:,.2f})."
        )

    return tb, warnings
