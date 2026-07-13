"""
Notes to Accounts Generator.

Builds the ledger-level breakup behind each Balance Sheet / P&L sub-head,
keyed by note_ref (e.g. "Note 5 - Property, Plant and Equipment") so the
Excel/PDF exporters can render one note per schedule with full ledger detail
and current-year/previous-year columns, matching how a real signed financial
statement is laid out.
"""
from __future__ import annotations

from dataclasses import dataclass

from schedule3_engine.core.statement_generator import BalanceSheet, ProfitAndLoss, LineItem


@dataclass
class Note:
    note_ref: str
    title: str
    line_items: list[LineItem]
    total_current_year: float
    total_previous_year: float


STANDARD_ACCOUNTING_POLICIES = {
    "Basis of Preparation": (
        "The financial statements have been prepared in accordance with the "
        "provisions of the Companies Act, 2013 and comply in all material "
        "respects with the applicable Accounting Standards notified under "
        "Section 133 of the Act, read with Rule 7 of the Companies (Accounts) "
        "Rules, 2014, and the relevant provisions of the Act, presented in the "
        "format prescribed under Schedule III to the Companies Act, 2013."
    ),
    "Revenue Recognition": (
        "Revenue from the sale of goods is recognized when significant risks "
        "and rewards of ownership are transferred to the buyer, usually on "
        "dispatch or delivery, and is measured at the fair value of "
        "consideration received or receivable, net of returns, trade "
        "discounts, and applicable GST. Revenue from services is recognized "
        "on completion of the service or proportionately over the period of "
        "the contract, as applicable. Interest income is recognized on a "
        "time-proportion basis and dividend income when the right to receive "
        "payment is established."
    ),
    "Property, Plant and Equipment": (
        "Property, Plant and Equipment are stated at cost of acquisition or "
        "construction, less accumulated depreciation and accumulated "
        "impairment losses, if any. Cost includes purchase price, import "
        "duties, non-refundable taxes, and any directly attributable cost of "
        "bringing the asset to its working condition for its intended use. "
        "Depreciation is provided on the Written Down Value / Straight Line "
        "Method over the useful life of the assets as prescribed under "
        "Schedule II to the Companies Act, 2013."
    ),
    "Inventories": (
        "Inventories are valued at the lower of cost and net realizable "
        "value. Cost is determined on a First-In-First-Out / Weighted "
        "Average basis and includes all costs of purchase, costs of "
        "conversion, and other costs incurred in bringing the inventories to "
        "their present location and condition."
    ),
    "Borrowing Costs": (
        "Borrowing costs directly attributable to the acquisition or "
        "construction of a qualifying asset are capitalized as part of the "
        "cost of that asset until the asset is ready for its intended use. "
        "All other borrowing costs are recognized as an expense in the "
        "Statement of Profit and Loss in the period in which they are "
        "incurred."
    ),
    "Income Taxes": (
        "Tax expense comprises current tax and deferred tax. Current tax is "
        "measured at the amount expected to be paid to the tax authorities "
        "using the applicable tax rates and tax laws. Deferred tax is "
        "recognized on timing differences between taxable income and "
        "accounting income, subject to the consideration of prudence, and is "
        "measured using tax rates that have been enacted or substantively "
        "enacted by the balance sheet date."
    ),
    "Cash Flow Statement": (
        "The Cash Flow Statement has been prepared under the indirect "
        "method as set out in the applicable Accounting Standard on Cash "
        "Flow Statements, whereby profit before tax is adjusted for the "
        "effects of transactions of a non-cash nature, deferrals or "
        "accruals of past or future cash receipts or payments, and items of "
        "income or expense associated with investing or financing cash "
        "flows."
    ),
    "Financial Instruments": (
        "Financial assets and financial liabilities are recognized when the "
        "Company becomes a party to the contractual provisions of the "
        "instrument. Financial assets and liabilities are initially "
        "measured at fair value and subsequently measured at amortized cost "
        "or fair value depending on their classification and the Company's "
        "business model for managing them."
    ),
    "Leases": (
        "Leases are classified as finance leases whenever the terms of the "
        "lease transfer substantially all the risks and rewards of "
        "ownership to the lessee. All other leases are classified as "
        "operating leases, and the related lease rentals are recognized as "
        "an expense in the Statement of Profit and Loss on a straight-line "
        "basis over the lease term."
    ),
    "Employee Benefits": (
        "Short-term employee benefits, including salaries, wages, and bonus, "
        "are recognized as an expense at the undiscounted amount in the "
        "Statement of Profit and Loss for the period in which the related "
        "service is rendered. Post-employment benefits such as gratuity are "
        "accounted for on the basis of actuarial valuation, or on a "
        "reasonable estimate basis where actuarial valuation has not been "
        "obtained."
    ),
    "Foreign Currency Transactions": (
        "Transactions in foreign currency are recorded at the exchange rate "
        "prevailing on the date of the transaction. Monetary assets and "
        "liabilities denominated in foreign currency are translated at the "
        "exchange rate prevailing at the balance sheet date, and the "
        "resulting exchange differences are recognized in the Statement of "
        "Profit and Loss."
    ),
    "Impairment of Assets": (
        "The carrying amounts of assets are reviewed at each balance sheet "
        "date to determine whether there is any indication of impairment. "
        "If any such indication exists, the recoverable amount is estimated, "
        "and an impairment loss is recognized in the Statement of Profit and "
        "Loss to the extent the carrying amount exceeds the recoverable "
        "amount."
    ),
    "Provisions, Contingent Liabilities and Contingent Assets": (
        "Provisions are recognized when the Company has a present obligation "
        "as a result of a past event, it is probable that an outflow of "
        "resources will be required to settle the obligation, and a "
        "reliable estimate can be made of the amount of the obligation. "
        "Contingent liabilities are disclosed when there is a possible "
        "obligation or a present obligation that may, but probably will "
        "not, require an outflow of resources. Contingent assets are "
        "neither recognized nor disclosed in the financial statements."
    ),
}


def generate_notes(bs: BalanceSheet, pnl: ProfitAndLoss) -> list[Note]:
    """Roll up every ledger line item under its note_ref, in the order they
    were encountered, producing one Note object per distinct note_ref."""
    notes_map: dict[str, Note] = {}

    def ingest(sub_heads):
        for sh in sub_heads:
            for item in sh.ledgers:
                ref = item.note_ref or f"Note - {sh.sub_head}"
                if ref not in notes_map:
                    title = ref.split(" - ", 1)[-1] if " - " in ref else ref
                    notes_map[ref] = Note(note_ref=ref, title=title, line_items=[],
                                           total_current_year=0.0, total_previous_year=0.0)
                notes_map[ref].line_items.append(item)
                notes_map[ref].total_current_year = round(
                    notes_map[ref].total_current_year + item.current_year, 2)
                notes_map[ref].total_previous_year = round(
                    notes_map[ref].total_previous_year + item.previous_year, 2)

    for major in bs.equity_and_liabilities:
        ingest(major.sub_heads)
    for major in bs.assets:
        ingest(major.sub_heads)
    for sh in pnl.revenue:
        ingest([sh])
    for sh in pnl.expenses:
        ingest([sh])

    # Sort by note number if the ref starts with "Note N"
    def sort_key(n: Note):
        import re
        m = re.match(r"Note\s+(\d+)", n.note_ref)
        return int(m.group(1)) if m else 999

    return sorted(notes_map.values(), key=sort_key)


def generate_related_party_placeholder() -> str:
    return (
        "No related party transactions were identified from the Trial "
        "Balance ledger names. Please confirm with management whether any "
        "transactions with directors, key managerial personnel, or their "
        "relatives (as defined under Section 2(76) of the Companies Act, "
        "2013 and Ind AS 24 / AS 18) occurred during the year, for "
        "appropriate disclosure under this note."
    )


def generate_msme_placeholder() -> str:
    return (
        "Based on information available with the Company, no supplier has "
        "been identified as registered under the Micro, Small and Medium "
        "Enterprises Development Act, 2006. This note requires confirmation "
        "from vendor master data / vendor confirmations before finalization, "
        "as required under Section 22 of the MSMED Act, 2006."
    )
