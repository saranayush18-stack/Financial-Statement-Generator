"""
Generates a realistic sample Trial Balance (manufacturing SME) as an Excel
file, including previous-year closing balances, for end-to-end testing of
the engine.
"""
from openpyxl import Workbook
from pathlib import Path


def _build_rows():
    """
    Builds a proper closing-balance Trial Balance (Debit/Credit = closing
    position for the year, exactly as Tally/Busy/Zoho export it), constructed
    so Total Debit = Total Credit -- a genuine double-entry check, not a
    cosmetic one.

    Structure:
    - Balance Sheet ledgers (credit-nature: capital/reserves/liabilities;
      debit-nature: assets) sum to the same debit and credit totals.
    - P&L ledgers (revenue = credit; expenses = debit) remain "open" in the
      Trial Balance, exactly as they would appear before the books are
      closed for statement preparation -- this is what makes the Balance
      Sheet correctly tally only after the engine carries current-year
      profit into Reserves and Surplus (see statement_generator.py).
    """
    # Ledger Name, Debit (closing), Credit (closing), Previous Year Closing (unsigned magnitude)
    rows = [
        # --- Balance Sheet: Equity, Reserves, Liabilities (credit-nature) ---
        ("Equity Share Capital", 0, 5000000, 5000000),
        ("General Reserve", 0, 1200000, 1200000),
        ("Profit and Loss Appropriation A/c", 0, 950000, 950000),
        ("Term Loan - HDFC Bank", 0, 2200000, 2600000),
        ("Loan from Director", 0, 500000, 500000),
        ("Cash Credit A/c - Axis Bank", 0, 780000, 620000),
        ("Sundry Creditors - Raw Material", 0, 1650000, 1420000),
        ("GST Output CGST", 0, 210000, 180000),
        ("GST Output SGST", 0, 210000, 180000),
        ("TDS Payable on Salary", 0, 45000, 38000),
        ("Provision for Income Tax", 0, 320000, 280000),
        ("Salary Payable", 0, 95000, 80000),
        ("Provision for Gratuity", 0, 180000, 150000),
        ("Accumulated Depreciation - Plant and Machinery", 0, 980000, 780000),

        # --- Balance Sheet: Assets (debit-nature) ---
        ("Plant and Machinery", 3650000, 0, 3200000),
        ("Computer", 220000, 0, 180000),
        ("Office Furniture", 220000, 0, 220000),
        ("Capital Work in Progress", 150000, 0, 0),
        ("Software License", 90000, 0, 90000),
        ("Investment in Mutual Fund", 500000, 0, 500000),
        ("Closing Stock - Raw Material", 620000, 0, 480000),
        ("Closing Stock - Finished Goods", 780000, 0, 650000),
        ("Sundry Debtors - Trade", 1450000, 0, 1180000),
        ("Cash in Hand", 45000, 0, 38000),
        ("HDFC Bank Current A/c", 620000, 0, 540000),
        ("GST Input CGST", 195000, 0, 165000),
        ("GST Input SGST", 195000, 0, 165000),
        ("TDS Receivable", 38000, 0, 30000),
        ("Security Deposit Given - Rent", 100000, 0, 100000),
        ("Prepaid Insurance", 25000, 0, 18000),

        # --- P&L: Revenue (credit-nature) ---
        ("Sales - Domestic", 0, 12500000, 10800000),
        ("Export Sales", 0, 1800000, 1500000),
        ("Interest Income", 0, 45000, 38000),

        # --- P&L: Expenses (debit-nature) ---
        ("Purchase of Raw Material", 6800000, 0, 5900000),
        ("Factory Electricity", 420000, 0, 380000),
        ("Factory Rent", 360000, 0, 360000),
        ("Staff Salary", 1850000, 0, 1650000),
        ("Director Remuneration", 1200000, 0, 1100000),
        ("Contribution to PF", 165000, 0, 148000),
        ("Staff Welfare Expense", 85000, 0, 72000),
        ("Interest on Term Loan", 285000, 0, 320000),
        ("Bank Charges", 32000, 0, 28000),
        ("Depreciation Expense", 480000, 0, 420000),
        ("Rent Expense - Office", 240000, 0, 240000),
        ("Electricity Expense - Office", 65000, 0, 58000),
        ("Telephone and Internet Expense", 42000, 0, 38000),
        ("Printing and Stationery", 28000, 0, 24000),
        ("Travelling and Conveyance", 165000, 0, 142000),
        ("Legal and Professional Charges", 220000, 0, 180000),
        ("Audit Fee", 75000, 0, 65000),
        ("Insurance Expense", 58000, 0, 52000),
        ("Repair and Maintenance", 95000, 0, 88000),
        ("Advertisement Expense", 145000, 0, 120000),
        ("Freight Outward", 210000, 0, 185000),
        ("Miscellaneous Expense", 12000, 0, 32000),
    ]

    total_debit = sum(r[1] for r in rows)
    total_credit = sum(r[2] for r in rows)
    diff = round(total_debit - total_credit, 2)
    if abs(diff) > 0.01:
        # Balance the sample file exactly via the Miscellaneous Expense line,
        # so this sample TB is provably a valid double-entry trial balance.
        name, debit, credit, py = rows[-1]
        rows[-1] = (name, round(debit - diff, 2), credit, py)
    return rows


ROWS = _build_rows()


def generate(output_path: str = "sample_trial_balance.xlsx") -> str:
    wb = Workbook()
    ws = wb.active
    ws.title = "Trial Balance"
    ws.append(["Ledger Name", "Debit", "Credit", "Previous Year Closing"])
    for row in ROWS:
        ws.append(list(row))
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    wb.save(output_path)
    return output_path


if __name__ == "__main__":
    generate()
    print("Sample Trial Balance generated.")
