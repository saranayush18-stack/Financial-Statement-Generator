"""
Run the Schedule III engine on YOUR OWN Trial Balance.

HOW TO USE
----------
1. This file lives INSIDE the schedule3_engine folder, alongside models.py,
   streamlit_app.py, etc. Keep it there.
2. Edit the CONFIG section below: point TB_PATH at your Excel/CSV Trial
   Balance and fill in your company details.
3. Run (from inside this folder):  python run_my_trial_balance.py

WHAT YOUR TRIAL BALANCE FILE SHOULD LOOK LIKE
----------------------------------------------
An Excel or CSV with (at minimum) these columns -- header names are
flexible, the parser recognizes common variants (e.g. "Ledger" or
"Account Name" both work for the ledger name column):
    Ledger Name | Debit | Credit | Previous Year Closing (optional)
Debit/Credit should be each ledger's CLOSING position for the year
(exactly what Tally/Busy/Zoho/QuickBooks export), not a movement.

WHAT HAPPENS TO UNMAPPED LEDGERS
---------------------------------
Any ledger the rule engine can't classify is printed to the console so you
can see exactly what needs a manual mapping. For a first working version,
those ledgers are simply left out of the statements (with a warning) --
tell me the mapping and I can hardcode it into your classification rules
permanently.
"""
from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from models import Company
from core.tb_parser import parse_trial_balance
from core.mapping_store import MappingStore, resolve_mapping
from core.validator import validate, summarize_issues
from core.statement_generator import (
    generate_balance_sheet, generate_profit_and_loss, generate_cash_flow_indirect,
    carry_profit_into_reserves,
)
from core.notes_generator import generate_notes
from core.ratios import compute_ratios
from core.soce_generator import generate_soce, soce_reconciles_to_balance_sheet
from core.ageing import parse_ageing_file, build_ageing_grid, unavailable_grid, ageing_validation_issues
from export.excel_export import build_workbook, save_workbook
from export.pdf_export import build_pdf


# ============================================================================
# CONFIG -- edit this section for your client
# ============================================================================

TB_PATH = "my_trial_balance.xlsx"          # path to your Trial Balance file

COMPANY_NAME = "Your Client Company Pvt Ltd"
CIN = ""                                    # e.g. "U29100MH2015PTC123456" (optional)
PAN = ""
GSTIN = ""
REGISTERED_OFFICE = ""
AUDITOR = ""                                # e.g. "M/s ABC & Associates, Chartered Accountants"
DIRECTORS = []                              # e.g. ["Mr. Rajesh Sharma", "Mrs. Priya Sharma"]

FY_START = date(2025, 4, 1)
FY_END = date(2026, 3, 31)
FY_LABEL = "FY 2025-26 (1 April 2025 to 31 March 2026)"

# Optional: party-wise ageing files (Party Name / Amount / Due Date columns).
# Leave as None if you don't have these yet -- the engine will produce a
# clean "ageing not available" placeholder instead of guessing.
RECEIVABLES_AGEING_PATH = None              # e.g. "receivables_ageing.xlsx"
PAYABLES_AGEING_PATH = None                 # e.g. "payables_ageing.xlsx"

OUTPUT_DIR = "output"

# ============================================================================


def main():
    output_dir = Path(OUTPUT_DIR)
    output_dir.mkdir(parents=True, exist_ok=True)

    company = Company(
        name=COMPANY_NAME, cin=CIN or None, pan=PAN or None, gstin=GSTIN or None,
        registered_office=REGISTERED_OFFICE or None, auditor=AUDITOR or None,
        directors=DIRECTORS, financial_year_start=FY_START, financial_year_end=FY_END,
        company_id=1,
    )

    print(f"Parsing {TB_PATH} ...")
    tb, parse_warnings = parse_trial_balance(TB_PATH, company, FY_LABEL)
    for w in parse_warnings:
        print(f"  WARNING: {w}")
    print(f"  {len(tb.ledgers)} ledgers found. Balanced: {tb.is_balanced()}")

    store = MappingStore(str(output_dir / "mappings.db"))
    mappings, unmapped = {}, []
    for ledger in tb.ledgers:
        resolved = resolve_mapping(store, company.company_id, ledger.ledger_name)
        if resolved:
            mappings[ledger.ledger_name] = resolved
            if resolved.source == "RULE_ENGINE":
                store.save_company_mapping(company.company_id, resolved, user_name="ca_user")
        else:
            unmapped.append(ledger.ledger_name)

    if unmapped:
        print(f"\n{len(unmapped)} ledger(s) could not be auto-classified -- excluded from statements:")
        for name in unmapped:
            print(f"  - {name}")
        print("Tell me these names and I'll add rules so they classify automatically next time.\n")

    issues = validate(tb, mappings)

    bs = generate_balance_sheet(tb, mappings)
    pnl = generate_profit_and_loss(tb, mappings)
    bs = carry_profit_into_reserves(bs, pnl)
    cash_flow = generate_cash_flow_indirect(tb, mappings, pnl, bs)

    soce = generate_soce(bs, pnl)
    if not soce_reconciles_to_balance_sheet(soce, bs):
        print("WARNING: SOCE does not reconcile to the Balance Sheet -- check reserve mappings.")

    def _bs_amount(sub_head_name: str) -> float:
        for section in (bs.equity_and_liabilities, bs.assets):
            for major in section:
                for sh in major.sub_heads:
                    if sh.sub_head == sub_head_name:
                        return sh.current_year
        return 0.0

    if RECEIVABLES_AGEING_PATH:
        try:
            items = parse_ageing_file(RECEIVABLES_AGEING_PATH)
            receivables_ageing = build_ageing_grid("Trade Receivables", items, as_of=FY_END,
                                                     balance_sheet_amount=_bs_amount("Trade Receivables"))
        except ValueError as exc:
            receivables_ageing = unavailable_grid("Trade Receivables", FY_END, str(exc))
    else:
        receivables_ageing = unavailable_grid("Trade Receivables", FY_END,
                                                "no party-wise ledger with due dates was supplied.")

    if PAYABLES_AGEING_PATH:
        try:
            items = parse_ageing_file(PAYABLES_AGEING_PATH)
            payables_ageing = build_ageing_grid("Trade Payables", items, as_of=FY_END,
                                                  balance_sheet_amount=_bs_amount("Trade Payables"))
        except ValueError as exc:
            payables_ageing = unavailable_grid("Trade Payables", FY_END, str(exc))
    else:
        payables_ageing = unavailable_grid("Trade Payables", FY_END,
                                             "no party-wise ledger with due dates was supplied.")

    issues += ageing_validation_issues(receivables_ageing)
    issues += ageing_validation_issues(payables_ageing)

    notes = generate_notes(bs, pnl)
    ratios = compute_ratios(bs, pnl)

    wb = build_workbook(company, FY_LABEL, tb, mappings, bs, pnl, cash_flow, notes, issues, ratios,
                         soce=soce, receivables_ageing=receivables_ageing, payables_ageing=payables_ageing)
    excel_path = save_workbook(wb, str(output_dir / "Financial_Statements.xlsx"))
    pdf_path = build_pdf(str(output_dir / "Financial_Statements.pdf"), company, FY_LABEL,
                          bs, pnl, cash_flow, notes,
                          soce=soce, receivables_ageing=receivables_ageing, payables_ageing=payables_ageing)

    print("\n=== SUMMARY ===")
    print(f"Balance Sheet tallies: {bs.is_tallied}")
    print(f"Total Assets (CY): {bs.total_assets_cy:,.2f}")
    print(f"Total Equity & Liabilities (CY): {bs.total_equity_and_liabilities_cy:,.2f}")
    print(f"Profit After Tax (CY): {pnl.profit_after_tax_cy:,.2f}")
    print(f"Validation: {summarize_issues(issues)}")
    print(f"\nExcel: {excel_path}")
    print(f"PDF:   {pdf_path}")


if __name__ == "__main__":
    main()
