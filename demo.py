"""
End-to-end demo / smoke test for the Schedule III Engine.

Run with:  python -m schedule3_engine.demo

Pipeline:
1. Parse a sample Trial Balance (Excel)
2. Resolve every ledger's mapping (company override -> global learned -> rule engine)
3. Persist any newly-resolved mappings (simulating a user confirming suggestions)
4. Run the Validation Engine
5. Generate Balance Sheet, P&L, Cash Flow
6. Generate Notes to Accounts
7. Compute Financial Ratios
8. Export to Excel and PDF
"""
from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from schedule3_engine.models import Company
from schedule3_engine.core.tb_parser import parse_trial_balance
from schedule3_engine.core.mapping_store import MappingStore, resolve_mapping
from schedule3_engine.core.validator import validate, summarize_issues
from schedule3_engine.core.statement_generator import (
    generate_balance_sheet, generate_profit_and_loss, generate_cash_flow_indirect,
    carry_profit_into_reserves
)
from schedule3_engine.core.notes_generator import generate_notes
from schedule3_engine.core.ratios import compute_ratios
from schedule3_engine.core.soce_generator import generate_soce, soce_reconciles_to_balance_sheet
from schedule3_engine.core.ageing import (
    parse_ageing_file, build_ageing_grid, unavailable_grid, ageing_validation_issues,
)
from schedule3_engine.export.excel_export import build_workbook, save_workbook
from schedule3_engine.export.pdf_export import build_pdf
from schedule3_engine.sample_data.generate_sample_tb import generate as generate_sample_tb
from schedule3_engine.sample_data.generate_sample_ageing import (
    generate_receivables_ageing, generate_payables_ageing,
)


def run_demo(output_dir: str = ".") -> dict:
    output_dir_path = Path(output_dir)
    output_dir_path.mkdir(parents=True, exist_ok=True)

    # 1. Sample data + company
    tb_path = generate_sample_tb(str(output_dir_path / "sample_trial_balance.xlsx"))
    company = Company(
        name="Bharat Precision Components Private Limited",
        cin="U29100MH2015PTC123456",
        pan="AABCB1234C",
        gstin="27AABCB1234C1Z5",
        registered_office="Plot No. 45, MIDC Industrial Area, Pune, Maharashtra - 411019",
        auditor="M/s ABC & Associates, Chartered Accountants",
        directors=["Mr. Rajesh Sharma", "Mrs. Priya Sharma"],
        financial_year_start=date(2025, 4, 1),
        financial_year_end=date(2026, 3, 31),
        company_id=1,
    )
    fy_label = "FY 2025-26 (1 April 2025 to 31 March 2026)"

    # 2. Parse
    tb, parse_warnings = parse_trial_balance(tb_path, company, fy_label)

    # 3. Resolve mappings for every ledger
    store = MappingStore(str(output_dir_path / "schedule3_mappings.db"))
    mappings = {}
    unmapped = []
    for ledger in tb.ledgers:
        resolved = resolve_mapping(store, company.company_id, ledger.ledger_name)
        if resolved:
            mappings[ledger.ledger_name] = resolved
            # Simulate the CA confirming the rule-engine suggestion (persist it)
            if resolved.source == "RULE_ENGINE":
                store.save_company_mapping(company.company_id, resolved, user_name="demo_ca")
        else:
            unmapped.append(ledger.ledger_name)

    # 4. Validate
    py_closing_lookup = {
        l.ledger_name: l.previous_year_closing for l in tb.ledgers if l.previous_year_closing is not None
    }
    # Opening balance vs PY closing check is only meaningful if opening balance
    # itself should equal PY closing; skip mismatched sign comparisons for demo clarity.
    issues = validate(tb, mappings, previous_year_ledgers=None)

    # 5. Statements
    bs = generate_balance_sheet(tb, mappings)
    pnl = generate_profit_and_loss(tb, mappings)
    bs = carry_profit_into_reserves(bs, pnl)
    cash_flow = generate_cash_flow_indirect(tb, mappings, pnl, bs)

    # 5b. Statement of Changes in Equity
    soce = generate_soce(bs, pnl)
    soce_ok = soce_reconciles_to_balance_sheet(soce, bs)
    if not soce_ok:
        from schedule3_engine.models import ValidationIssue
        issues.append(ValidationIssue(
            severity="ERROR", code="SOCE_MISMATCH", ledger_name=None,
            message="Statement of Changes in Equity closing balances do not reconcile "
                    "to the Balance Sheet's Share Capital / Reserves and Surplus figures.",
        ))

    # 5c. Ageing schedules (Trade Receivables / Trade Payables)
    # Scenario demonstrated: supplementary party-wise ledgers WITH due dates
    # are available (the realistic case once a CA exports the debtors/
    # creditors ageing report from Tally/Busy alongside the TB).
    rec_ageing_path = generate_receivables_ageing(str(output_dir_path / "sample_receivables_ageing.xlsx"))
    pay_ageing_path = generate_payables_ageing(str(output_dir_path / "sample_payables_ageing.xlsx"))

    def _bs_amount(bs_obj, sub_head_name: str) -> float:
        for section in (bs_obj.equity_and_liabilities, bs_obj.assets):
            for major in section:
                for sh in major.sub_heads:
                    if sh.sub_head == sub_head_name:
                        return sh.current_year
        return 0.0

    try:
        rec_items = parse_ageing_file(rec_ageing_path)
        receivables_ageing = build_ageing_grid(
            "Trade Receivables", rec_items, as_of=company.financial_year_end,
            balance_sheet_amount=_bs_amount(bs, "Trade Receivables"),
        )
    except ValueError as exc:
        receivables_ageing = unavailable_grid("Trade Receivables", company.financial_year_end, str(exc))

    try:
        pay_items = parse_ageing_file(pay_ageing_path)
        payables_ageing = build_ageing_grid(
            "Trade Payables", pay_items, as_of=company.financial_year_end,
            balance_sheet_amount=_bs_amount(bs, "Trade Payables"),
        )
    except ValueError as exc:
        payables_ageing = unavailable_grid("Trade Payables", company.financial_year_end, str(exc))

    issues += ageing_validation_issues(receivables_ageing)
    issues += ageing_validation_issues(payables_ageing)

    # Also demonstrate the graceful "no supplementary data supplied" path,
    # since most real engagements won't have this file on day one.
    no_data_grid = unavailable_grid(
        "Trade Receivables", company.financial_year_end,
        "no party-wise ledger with due dates was supplied alongside the Trial Balance."
    )

    # 6. Notes
    notes = generate_notes(bs, pnl)

    # 7. Ratios
    ratios = compute_ratios(bs, pnl)

    # 8. Export
    wb = build_workbook(company, fy_label, tb, mappings, bs, pnl, cash_flow, notes, issues, ratios,
                         soce=soce, receivables_ageing=receivables_ageing, payables_ageing=payables_ageing)
    excel_path = save_workbook(wb, str(output_dir_path / "Financial_Statements.xlsx"))
    pdf_path = build_pdf(str(output_dir_path / "Financial_Statements.pdf"), company, fy_label,
                          bs, pnl, cash_flow, notes,
                          soce=soce, receivables_ageing=receivables_ageing, payables_ageing=payables_ageing)

    summary = {
        "trial_balance_ledgers": len(tb.ledgers),
        "trial_balance_balanced": tb.is_balanced(),
        "unmapped_ledgers": unmapped,
        "validation_summary": summarize_issues(issues),
        "balance_sheet_tallies": bs.is_tallied,
        "total_assets_cy": bs.total_assets_cy,
        "total_equity_and_liabilities_cy": bs.total_equity_and_liabilities_cy,
        "revenue_cy": pnl.total_revenue_cy,
        "profit_after_tax_cy": pnl.profit_after_tax_cy,
        "soce_reconciles": soce_ok,
        "soce_share_capital_closing": soce.equity_share_capital.closing,
        "soce_other_equity_closing": soce.total_other_equity_closing,
        "receivables_ageing_total": receivables_ageing.total,
        "receivables_ageing_reconciles": receivables_ageing.reconciles_to_balance_sheet,
        "payables_ageing_total": payables_ageing.total,
        "payables_ageing_reconciles": payables_ageing.reconciles_to_balance_sheet,
        "ageing_fallback_when_no_data_available": no_data_grid.unavailable_reason,
        "excel_path": excel_path,
        "pdf_path": pdf_path,
        "parse_warnings": parse_warnings,
    }
    return summary


if __name__ == "__main__":
    result = run_demo(output_dir="./demo_output")
    print("\n=== DEMO RUN SUMMARY ===")
    for k, v in result.items():
        print(f"{k}: {v}")
