"""
Generates a sample party-wise ageing input file (the supplementary data a
CA would export from Tally's "Bills Receivable/Payable" report) for the
demo. Amounts are constructed to reconcile exactly to the sample Trial
Balance's Trade Receivables (Rs. 14,50,000) and Trade Payables
(Rs. 16,50,000) figures.
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd


def generate_receivables_ageing(output_path: str) -> str:
    rows = [
        # Party, Amount, Due Date, Disputed, Doubtful
        ("Suresh Auto Components Pvt Ltd", 320000, "2026-02-15", "N", "N"),
        ("Deccan Engineering Works", 275000, "2025-12-01", "N", "N"),
        ("Kaveri Fabricators", 210000, "2025-09-10", "N", "N"),
        ("National Bearings Co.", 180000, "2025-05-20", "N", "N"),
        ("Om Sai Industries", 150000, "2024-11-05", "N", "N"),
        ("Vintage Tool Traders", 90000, "2023-06-15", "Y", "N"),
        ("Ashok Metal Works (disputed, doubtful)", 125000, "2022-01-10", "Y", "Y"),
        ("Balance from unbilled sales (not yet due)", 100000, "2026-04-15", "N", "N"),
    ]
    df = pd.DataFrame(rows, columns=["Party Name", "Amount", "Due Date", "Disputed", "Doubtful"])
    df.to_excel(output_path, index=False)
    return output_path


def generate_payables_ageing(output_path: str) -> str:
    rows = [
        ("Bharat Steel Suppliers", 450000, "2026-01-20", "N", "N"),
        ("Precision Casting Co.", 380000, "2025-10-05", "N", "N"),
        ("Metro Packaging Ltd", 260000, "2025-08-12", "N", "N"),
        ("Standard Fasteners Pvt Ltd", 220000, "2025-04-01", "N", "N"),
        ("Anand Machine Tools", 180000, "2024-09-18", "N", "N"),
        ("Old Vendor Dues (disputed)", 100000, "2023-03-01", "Y", "N"),
        ("Advance from customer adjusted against PO (not yet due)", 60000, "2026-05-01", "N", "N"),
    ]
    df = pd.DataFrame(rows, columns=["Party Name", "Amount", "Due Date", "Disputed", "Doubtful"])
    df.to_excel(output_path, index=False)
    return output_path


if __name__ == "__main__":
    out_dir = Path(__file__).resolve().parent
    generate_receivables_ageing(str(out_dir / "sample_receivables_ageing.xlsx"))
    generate_payables_ageing(str(out_dir / "sample_payables_ageing.xlsx"))
    print("Sample ageing files generated.")
