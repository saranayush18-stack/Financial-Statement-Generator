"""
Validation Engine.

Runs a battery of sanity checks on the Trial Balance + resolved mappings
before statements are generated, so mapping errors are caught early rather
than surfacing as a wrong Balance Sheet.
"""
from __future__ import annotations

from models import (
    TrialBalance, MappingEntry, ValidationIssue, Nature, Statement
)


def validate(
    tb: TrialBalance,
    mappings: dict[str, MappingEntry],
    previous_year_ledgers: dict[str, float] | None = None,
) -> list[ValidationIssue]:
    """
    mappings: ledger_name -> MappingEntry (already resolved; unmapped ledgers
              should not be present, or should be flagged separately by the
              caller as "pending mapping" before validation runs).
    """
    issues: list[ValidationIssue] = []
    previous_year_ledgers = previous_year_ledgers or {}

    # 1. Debit = Credit
    if not tb.is_balanced():
        diff = round(tb.total_debit() - tb.total_credit(), 2)
        issues.append(ValidationIssue(
            severity="ERROR", code="TB_NOT_BALANCED", ledger_name=None,
            message=f"Trial Balance does not tie out (difference of {diff:,.2f}). "
                    "Financial statements cannot be certified until resolved.",
            amount=diff,
        ))

    by_ledger = {l.ledger_name: l for l in tb.ledgers}

    for ledger_name, ledger in by_ledger.items():
        mapping = mappings.get(ledger_name)
        if mapping is None:
            issues.append(ValidationIssue(
                severity="WARNING", code="UNMAPPED_LEDGER", ledger_name=ledger_name,
                message=f"'{ledger_name}' has no confirmed Schedule III mapping.",
            ))
            continue

        closing = ledger.closing_balance
        sub_head = mapping.sub_head

        # 2. Negative cash / bank
        if sub_head == "Cash and Cash Equivalents" and closing < 0:
            issues.append(ValidationIssue(
                severity="ERROR", code="NEGATIVE_CASH", ledger_name=ledger_name,
                message=f"'{ledger_name}' shows a negative cash/bank balance of {closing:,.2f}.",
                amount=closing,
            ))

        # 3. Negative stock
        if sub_head == "Inventories" and closing < 0:
            issues.append(ValidationIssue(
                severity="ERROR", code="NEGATIVE_STOCK", ledger_name=ledger_name,
                message=f"'{ledger_name}' shows negative inventory of {closing:,.2f}.",
                amount=closing,
            ))

        # 4. Negative capital (share capital should not be a net debit)
        if sub_head == "Share Capital" and closing > 0:
            issues.append(ValidationIssue(
                severity="ERROR", code="NEGATIVE_CAPITAL", ledger_name=ledger_name,
                message=f"'{ledger_name}' (Share Capital) carries an unexpected debit "
                        f"balance of {closing:,.2f}; share capital should be credit in nature.",
                amount=closing,
            ))

        # 5. Trade receivable with a credit (negative) balance
        if sub_head == "Trade Receivables" and closing < 0:
            issues.append(ValidationIssue(
                severity="WARNING", code="RECEIVABLE_NEGATIVE", ledger_name=ledger_name,
                message=f"'{ledger_name}' (Trade Receivable) has a credit balance of "
                        f"{abs(closing):,.2f}; consider reclassifying as advance received "
                        "or trade payable.",
                amount=closing,
            ))

        # 6. Trade payable with a debit (negative) balance
        if sub_head == "Trade Payables" and closing > 0:
            issues.append(ValidationIssue(
                severity="WARNING", code="PAYABLE_NEGATIVE", ledger_name=ledger_name,
                message=f"'{ledger_name}' (Trade Payable) has a debit balance of "
                        f"{closing:,.2f}; consider reclassifying as advance to supplier "
                        "or trade receivable.",
                amount=closing,
            ))

        # 7. Nature mismatch: mapping expects Dr but ledger nets Cr, or vice versa
        expected_dr = mapping.nature == Nature.DEBIT
        if expected_dr and closing < -0.01:
            issues.append(ValidationIssue(
                severity="WARNING", code="NATURE_MISMATCH", ledger_name=ledger_name,
                message=f"'{ledger_name}' is mapped as a debit-nature account "
                        f"({sub_head}) but nets to a credit balance of {abs(closing):,.2f}. "
                        "Please verify the mapping or the entry.",
                amount=closing,
            ))
        if (not expected_dr) and closing > 0.01:
            issues.append(ValidationIssue(
                severity="WARNING", code="NATURE_MISMATCH", ledger_name=ledger_name,
                message=f"'{ledger_name}' is mapped as a credit-nature account "
                        f"({sub_head}) but nets to a debit balance of {closing:,.2f}. "
                        "Please verify the mapping or the entry.",
                amount=closing,
            ))

        # 8. Abnormal depreciation (P&L depreciation exceeding gross block is a red flag;
        #    exact gross block check happens in notes_generator, this is a lightweight guard)
        if sub_head == "Depreciation and Amortization Expense" and closing < 0:
            issues.append(ValidationIssue(
                severity="WARNING", code="DEPRECIATION_ABNORMAL", ledger_name=ledger_name,
                message=f"'{ledger_name}' shows a credit balance for depreciation "
                        f"expense of {abs(closing):,.2f}, which is unusual.",
                amount=closing,
            ))

        # 9. Opening balance vs previous year closing mismatch
        py_closing = previous_year_ledgers.get(ledger_name)
        if py_closing is not None and abs(py_closing - ledger.opening_balance) > 1:
            issues.append(ValidationIssue(
                severity="WARNING", code="OPENING_MISMATCH", ledger_name=ledger_name,
                message=f"'{ledger_name}' opening balance ({ledger.opening_balance:,.2f}) does not "
                        f"match previous year's closing balance ({py_closing:,.2f}).",
                amount=round(ledger.opening_balance - py_closing, 2),
            ))

    # 10. GST input vs output net check (informational, not an error)
    gst_input = sum(
        by_ledger[n].closing_balance for n, m in mappings.items()
        if m.note_ref and "Other Current Assets" == m.sub_head and n in by_ledger
        and any(k in n.lower() for k in ["gst", "itc", "input tax"])
    )
    gst_output = sum(
        by_ledger[n].closing_balance for n, m in mappings.items()
        if m.sub_head == "Other Current Liabilities" and n in by_ledger
        and any(k in n.lower() for k in ["gst"])
    )
    if gst_input or gst_output:
        issues.append(ValidationIssue(
            severity="INFO", code="GST_NET_POSITION", ledger_name=None,
            message=f"Net GST position: Input {gst_input:,.2f} vs Output {abs(gst_output):,.2f}. "
                    "Verify this matches the GSTR-3B for the year.",
        ))

    return issues


def summarize_issues(issues: list[ValidationIssue]) -> dict:
    return {
        "errors": len([i for i in issues if i.severity == "ERROR"]),
        "warnings": len([i for i in issues if i.severity == "WARNING"]),
        "info": len([i for i in issues if i.severity == "INFO"]),
        "total": len(issues),
    }
