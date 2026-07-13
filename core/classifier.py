"""
Ledger Classification Engine (rule-based, keyword matching).

Given a ledger name, suggests a Schedule III mapping using the ordered
keyword rules in data/classification_rules.py. This is intentionally
transparent and debuggable -- every suggestion can be traced back to the
exact rule and keyword that fired, which matters when a CA has to defend a
classification to a reviewing partner or auditor.

Design choice (per user preference): rule-based keyword matching, not an
LLM call, so classification is instant, free, deterministic, and works
fully offline. The MappingStore (mapping_store.py) persists user overrides
per company, so once a firm corrects a ledger's mapping, the engine will
never ask about that exact ledger name again for that company.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from schedule3_engine.data.classification_rules import RULES, normalize
from schedule3_engine.models import MappingEntry, Statement, CurrentNonCurrent, Nature


@dataclass
class ClassificationSuggestion:
    ledger_name: str
    matched: bool
    major_head: Optional[str] = None
    sub_head: Optional[str] = None
    statement: Optional[Statement] = None
    current_or_non_current: Optional[CurrentNonCurrent] = None
    nature: Optional[Nature] = None
    note_ref: Optional[str] = None
    matched_keyword: Optional[str] = None
    confidence: float = 0.0


def classify_ledger(ledger_name: str) -> ClassificationSuggestion:
    """Classify a single ledger name using the keyword rule table."""
    normalized = normalize(ledger_name)

    for keywords, major_head, sub_head, statement, cur_ncur, nature, note_ref in RULES:
        for kw in keywords:
            if kw in normalized:
                # Longer keyword matches are treated as higher confidence
                # (a more specific phrase matched, not just a short generic word).
                confidence = min(0.95, 0.55 + 0.05 * len(kw.split()))
                return ClassificationSuggestion(
                    ledger_name=ledger_name,
                    matched=True,
                    major_head=major_head,
                    sub_head=sub_head,
                    statement=statement,
                    current_or_non_current=cur_ncur,
                    nature=nature,
                    note_ref=note_ref,
                    matched_keyword=kw,
                    confidence=confidence,
                )

    return ClassificationSuggestion(ledger_name=ledger_name, matched=False)


def suggestion_to_mapping_entry(suggestion: ClassificationSuggestion) -> Optional[MappingEntry]:
    """Convert a matched suggestion into a MappingEntry (source=RULE_ENGINE)."""
    if not suggestion.matched:
        return None
    return MappingEntry(
        ledger_name=suggestion.ledger_name,
        major_head=suggestion.major_head,
        sub_head=suggestion.sub_head,
        statement=suggestion.statement,
        current_or_non_current=suggestion.current_or_non_current,
        nature=suggestion.nature,
        confidence=suggestion.confidence,
        source="RULE_ENGINE",
        note_ref=suggestion.note_ref,
    )


def classify_batch(ledger_names: list[str]) -> list[ClassificationSuggestion]:
    return [classify_ledger(name) for name in ledger_names]
