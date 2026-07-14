"""
Schedule III (Division I, Companies Act 2013) taxonomy plus a keyword-based
rule set used by the classification engine.

Design notes
------------
- Rules are stored as an ordered list. The FIRST matching rule wins, so more
  specific patterns are placed before generic catch-alls.
- Matching is done on a normalized ledger name (lowercased, punctuation
  stripped, extra whitespace collapsed) using substring/keyword tests -- no
  ML, no external API call, fully transparent and auditable.
- Every rule maps to: (major_head, sub_head, statement, current/non-current,
  nature, note_ref). This is exactly the tuple a MappingEntry needs.
- This table is a strong starting point for a typical Indian SME/manufacturing
  trial balance. It is NOT exhaustive -- ledgers that don't match anything
  fall through to classifier.py's "UNCLASSIFIED" bucket for manual mapping,
  and any manual mapping is persisted via mapping_store.py so the engine
  effectively "learns" the client's chart of accounts over time.
"""
from models import Statement, CurrentNonCurrent, Nature

BS = Statement.BALANCE_SHEET
PL = Statement.PROFIT_AND_LOSS
CUR = CurrentNonCurrent.CURRENT
NCUR = CurrentNonCurrent.NON_CURRENT
NA = CurrentNonCurrent.NOT_APPLICABLE
DR = Nature.DEBIT
CR = Nature.CREDIT

# ---------------------------------------------------------------------------
# Schedule III statement structure (used to drive statement_generator.py and
# excel_export.py ordering; NOT used for matching).
# ---------------------------------------------------------------------------
SCHEDULE_III_STRUCTURE = {
    "BALANCE_SHEET": {
        "EQUITY AND LIABILITIES": {
            "Shareholders' Funds": ["Share Capital", "Reserves and Surplus"],
            "Non-Current Liabilities": [
                "Long-Term Borrowings",
                "Deferred Tax Liabilities (Net)",
                "Other Long-Term Liabilities",
                "Long-Term Provisions",
            ],
            "Current Liabilities": [
                "Short-Term Borrowings",
                "Trade Payables",
                "Other Current Liabilities",
                "Short-Term Provisions",
            ],
        },
        "ASSETS": {
            "Non-Current Assets": [
                "Property, Plant and Equipment",
                "Capital Work-in-Progress",
                "Intangible Assets",
                "Non-Current Investments",
                "Long-Term Loans and Advances",
                "Other Non-Current Assets",
            ],
            "Current Assets": [
                "Current Investments",
                "Inventories",
                "Trade Receivables",
                "Cash and Cash Equivalents",
                "Short-Term Loans and Advances",
                "Other Current Assets",
            ],
        },
    },
    "PROFIT_AND_LOSS": {
        "Revenue": ["Revenue from Operations", "Other Income"],
        "Expenses": [
            "Cost of Materials Consumed",
            "Purchases of Stock-in-Trade",
            "Changes in Inventories of Finished Goods, WIP and Stock-in-Trade",
            "Employee Benefit Expense",
            "Finance Costs",
            "Depreciation and Amortization Expense",
            "Other Expenses",
        ],
        "Tax": ["Tax Expense"],
    },
}

# ---------------------------------------------------------------------------
# Keyword rules: (keywords, major_head, sub_head, statement, cur/ncur, nature, note_ref)
# ---------------------------------------------------------------------------
RULES: list[tuple] = [
    # --- Share capital / reserves ---
    (["share capital", "equity share", "paid up capital", "paid-up capital"],
     "Shareholders' Funds", "Share Capital", BS, NA, CR, "Note 1 - Share Capital"),
    (["general reserve", "retained earning", "surplus", "reserves and surplus",
      "profit and loss appropriation", "securities premium", "capital reserve"],
     "Shareholders' Funds", "Reserves and Surplus", BS, NA, CR, "Note 2 - Reserves and Surplus"),

    # --- Finance costs (checked BEFORE Borrowings so "Interest on Term Loan"
    #     doesn't fall through to the generic "term loan" Borrowings keyword) ---
    (["interest on loan", "interest on od", "interest on cc", "interest on term loan",
      "interest on cash credit", "interest expense", "interest paid", "loan processing fee",
      "bank charges", "finance cost"],
     "Expenses", "Finance Costs", PL, NA, DR, "Note 25 - Finance Costs"),

    # --- Depreciation (P&L expense line, checked BEFORE the fixed-asset section
    #     so "Depreciation Expense" doesn't fall through to the Accumulated
    #     Depreciation keyword, which is intentionally restricted to only match
    #     "accumulated depreciation" / "depreciation on <asset>" phrasing) ---
    (["depreciation expense", "amortization expense"],
     "Expenses", "Depreciation and Amortization Expense", PL, NA, DR, "Note 26 - Depreciation and Amortization"),

    # --- Borrowings ---
    (["term loan", "loan from director", "loan from bank", "debenture",
      "long term loan", "vehicle loan", "car loan", "unsecured loan"],
     "Non-Current Liabilities", "Long-Term Borrowings", BS, NCUR, CR, "Note 3 - Long-Term Borrowings"),
    (["cash credit", "overdraft", "od account", "working capital loan",
      "short term loan", "bank od"],
     "Current Liabilities", "Short-Term Borrowings", BS, CUR, CR, "Note 9 - Short-Term Borrowings"),

    # --- Trade payables / receivables ---
    (["sundry creditor", "trade payable", "creditors for", "creditor",
      "payable to supplier", "vendor payable"],
     "Current Liabilities", "Trade Payables", BS, CUR, CR, "Note 10 - Trade Payables"),
    (["sundry debtor", "trade receivable", "debtors", "receivable from customer",
      "debtor for"],
     "Current Assets", "Trade Receivables", BS, CUR, DR, "Note 15 - Trade Receivables"),

    # --- Statutory dues (GST / TDS / PF / ESI / PT / Income Tax) ---
    (["gst input", "input cgst", "input sgst", "input igst", "gst credit",
      "input tax credit", "itc "],
     "Current Assets", "Other Current Assets", BS, CUR, DR, "Note 17 - Other Current Assets"),
    (["gst output", "output cgst", "output sgst", "output igst", "gst payable",
      "gst liability"],
     "Current Liabilities", "Other Current Liabilities", BS, CUR, CR, "Note 11 - Other Current Liabilities"),
    (["tds payable", "tds on", "tax deducted at source payable"],
     "Current Liabilities", "Other Current Liabilities", BS, CUR, CR, "Note 11 - Other Current Liabilities"),
    (["tds receivable", "tds recoverable"],
     "Current Assets", "Other Current Assets", BS, CUR, DR, "Note 17 - Other Current Assets"),
    (["provision for income tax", "income tax payable", "advance tax"],
     "Current Liabilities", "Short-Term Provisions", BS, CUR, CR, "Note 13 - Short-Term Provisions"),
    (["pf payable", "provident fund payable", "esi payable", "professional tax payable"],
     "Current Liabilities", "Other Current Liabilities", BS, CUR, CR, "Note 11 - Other Current Liabilities"),

    # --- Fixed assets ---
    (["computer", "furniture", "office equipment", "plant and machinery",
      "plant & machinery", "vehicle", "building", "land", "machinery",
      "electrical fitting", "air conditioner", "fixed asset"],
     "Non-Current Assets", "Property, Plant and Equipment", BS, NCUR, DR, "Note 5 - Property, Plant and Equipment"),
    (["capital work in progress", "cwip", "capital wip"],
     "Non-Current Assets", "Capital Work-in-Progress", BS, NCUR, DR, "Note 6 - Capital Work-in-Progress"),
    (["goodwill", "software license", "software", "patent", "trademark",
      "copyright", "intangible"],
     "Non-Current Assets", "Intangible Assets", BS, NCUR, DR, "Note 7 - Intangible Assets"),
    (["depreciation", "accumulated depreciation"],
     "Non-Current Assets", "Property, Plant and Equipment", BS, NCUR, CR, "Note 5 - Property, Plant and Equipment"),

    # --- Investments ---
    (["investment in shares", "mutual fund", "fixed deposit above 12",
      "investment in subsidiary", "non current investment"],
     "Non-Current Assets", "Non-Current Investments", BS, NCUR, DR, "Note 8 - Non-Current Investments"),

    # --- Inventory ---
    (["stock in trade", "closing stock", "inventory", "raw material stock",
      "finished goods stock", "wip stock", "stock of"],
     "Current Assets", "Inventories", BS, CUR, DR, "Note 14 - Inventories"),

    # --- Cash & bank ---
    (["cash in hand", "cash on hand", "petty cash", "cash account"],
     "Current Assets", "Cash and Cash Equivalents", BS, CUR, DR, "Note 16 - Cash and Cash Equivalents"),
    (["bank account", "bank of", "current account", "hdfc", "icici", "sbi",
      "axis bank", "kotak", "bank balance"],
     "Current Assets", "Cash and Cash Equivalents", BS, CUR, DR, "Note 16 - Cash and Cash Equivalents"),

    # --- Loans & advances / prepaid ---
    (["security deposit given", "deposit paid", "advance to supplier",
      "advance to staff", "loan to employee", "staff advance"],
     "Current Assets", "Short-Term Loans and Advances", BS, CUR, DR, "Note 18 - Short-Term Loans and Advances"),
    (["prepaid expense", "prepaid insurance", "prepaid rent"],
     "Current Assets", "Other Current Assets", BS, CUR, DR, "Note 17 - Other Current Assets"),
    (["security deposit received", "deposit from customer", "advance from customer"],
     "Current Liabilities", "Other Current Liabilities", BS, CUR, CR, "Note 11 - Other Current Liabilities"),

    # --- Provisions ---
    (["provision for gratuity", "provision for leave encashment",
      "provision for warranty", "gratuity payable"],
     "Long-Term Provisions", "Long-Term Provisions", BS, NCUR, CR, "Note 4 - Long-Term Provisions"),
    (["provision for expenses", "outstanding expense", "salary payable",
      "audit fee payable", "expenses payable"],
     "Current Liabilities", "Short-Term Provisions", BS, CUR, CR, "Note 13 - Short-Term Provisions"),

    # --- Revenue ---
    (["sales", "revenue from operation", "service income", "export sales",
      "domestic sales", "income from service", "turnover"],
     "Revenue", "Revenue from Operations", PL, NA, CR, "Note 19 - Revenue from Operations"),
    (["interest income", "dividend income", "rent received", "commission received",
      "other income", "misc income", "profit on sale of asset", "discount received"],
     "Revenue", "Other Income", PL, NA, CR, "Note 20 - Other Income"),

    # --- Cost of materials / purchases ---
    (["purchase of raw material", "raw material consumed", "material purchase",
      "cost of material"],
     "Expenses", "Cost of Materials Consumed", PL, NA, DR, "Note 21 - Cost of Materials Consumed"),
    (["purchase of stock in trade", "trading purchase", "purchase - trading"],
     "Expenses", "Purchases of Stock-in-Trade", PL, NA, DR, "Note 22 - Purchases of Stock-in-Trade"),

    # --- Employee cost ---
    (["salary", "wages", "employee cost", "payroll", "staff welfare",
      "bonus", "gratuity expense", "leave encashment expense",
      "contribution to pf", "staff salary", "director remuneration"],
     "Expenses", "Employee Benefit Expense", PL, NA, DR, "Note 24 - Employee Benefit Expense"),

    # --- Finance costs ---
    (["interest on loan", "interest on od", "interest on cc", "bank charges",
      "loan processing fee", "finance cost", "interest expense", "interest paid"],
     "Expenses", "Finance Costs", PL, NA, DR, "Note 25 - Finance Costs"),

    # --- Depreciation (P&L expense line) ---
    (["depreciation expense", "amortization expense", "depreciation on"],
     "Expenses", "Depreciation and Amortization Expense", PL, NA, DR, "Note 26 - Depreciation and Amortization"),

    # --- Manufacturing / factory expenses ---
    (["factory electricity", "power and fuel", "factory rent", "factory expense",
      "manufacturing expense", "job work charge", "freight inward"],
     "Expenses", "Other Expenses", PL, NA, DR, "Note 27 - Other Expenses"),

    # --- Admin / selling / other expenses (broad catch-all, kept last among PL rules) ---
    (["rent expense", "office rent", "electricity expense", "telephone expense",
      "internet expense", "printing", "stationery", "travelling", "conveyance",
      "legal and professional", "audit fee", "consultancy fee", "insurance expense",
      "repair and maintenance", "advertisement", "commission paid", "freight outward",
      "courier", "postage", "office expense", "miscellaneous expense", "donation",
      "csr expense", "rates and taxes", "rounding off", "round off"],
     "Expenses", "Other Expenses", PL, NA, DR, "Note 27 - Other Expenses"),

    # --- Tax ---
    (["current tax", "provision for tax", "income tax expense", "deferred tax expense"],
     "Tax", "Tax Expense", PL, NA, DR, "Note 28 - Tax Expense"),
]


def normalize(name: str) -> str:
    """Lowercase, strip punctuation, collapse whitespace for keyword matching."""
    import re
    s = name.lower().strip()
    s = re.sub(r"[^a-z0-9\s]", " ", s)
    s = re.sub(r"\s+", " ", s)
    return s
