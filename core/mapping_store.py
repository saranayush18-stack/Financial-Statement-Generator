"""
Persistent Mapping Store.

Once a user confirms (or manually corrects) how a ledger maps to Schedule
III, that decision must never be asked again for that company -- and ideally
it should also help other companies with an identically-named ledger (e.g.
"HDFC Bank Current A/c" means the same thing for every client). This module
uses SQLite (swap-in-ready for PostgreSQL later; the SQL here is
vanilla-enough to work on both) with two tables:

- company_mapping: ledger -> mapping, scoped to one company (highest priority)
- global_mapping:  ledger -> mapping, learned across all companies over time
                    (used only when no company-specific mapping exists and
                    the rule engine also didn't match)

Lookup order for any ledger: company_mapping -> global_mapping -> rule engine
-> unmapped (ask the user).
"""
from __future__ import annotations

import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Optional

from schedule3_engine.models import MappingEntry, Statement, CurrentNonCurrent, Nature
from schedule3_engine.data.classification_rules import normalize

DEFAULT_DB_PATH = "schedule3_mappings.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS company_mapping (
    company_id INTEGER NOT NULL,
    ledger_key TEXT NOT NULL,          -- normalized ledger name
    ledger_name TEXT NOT NULL,         -- original display name (last seen)
    major_head TEXT NOT NULL,
    sub_head TEXT NOT NULL,
    statement TEXT NOT NULL,
    current_or_non_current TEXT NOT NULL,
    nature TEXT NOT NULL,
    note_ref TEXT,
    source TEXT NOT NULL DEFAULT 'MANUAL',
    updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (company_id, ledger_key)
);

CREATE TABLE IF NOT EXISTS global_mapping (
    ledger_key TEXT PRIMARY KEY,
    ledger_name TEXT NOT NULL,
    major_head TEXT NOT NULL,
    sub_head TEXT NOT NULL,
    statement TEXT NOT NULL,
    current_or_non_current TEXT NOT NULL,
    nature TEXT NOT NULL,
    note_ref TEXT,
    times_confirmed INTEGER DEFAULT 1,
    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS audit_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    company_id INTEGER,
    ledger_name TEXT,
    action TEXT,               -- MAPPED | REMAPPED | AI_SUGGESTED
    old_value TEXT,
    new_value TEXT,
    user_name TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
"""


class MappingStore:
    def __init__(self, db_path: str = DEFAULT_DB_PATH):
        self.db_path = db_path
        Path(db_path).parent.mkdir(parents=True, exist_ok=True) if Path(db_path).parent != Path("") else None
        with closing(self._connect()) as conn:
            conn.executescript(SCHEMA)
            conn.commit()

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.db_path)

    # ------------------------------------------------------------------
    # Lookups
    # ------------------------------------------------------------------
    def get_company_mapping(self, company_id: int, ledger_name: str) -> Optional[MappingEntry]:
        key = normalize(ledger_name)
        with closing(self._connect()) as conn:
            row = conn.execute(
                "SELECT major_head, sub_head, statement, current_or_non_current, nature, "
                "note_ref, source FROM company_mapping WHERE company_id=? AND ledger_key=?",
                (company_id, key),
            ).fetchone()
        if not row:
            return None
        return MappingEntry(
            ledger_name=ledger_name,
            major_head=row[0],
            sub_head=row[1],
            statement=Statement(row[2]),
            current_or_non_current=CurrentNonCurrent(row[3]),
            nature=Nature(row[4]),
            confidence=1.0,
            source=row[6],
            note_ref=row[5],
        )

    def get_global_mapping(self, ledger_name: str) -> Optional[MappingEntry]:
        key = normalize(ledger_name)
        with closing(self._connect()) as conn:
            row = conn.execute(
                "SELECT major_head, sub_head, statement, current_or_non_current, nature, "
                "note_ref FROM global_mapping WHERE ledger_key=?",
                (key,),
            ).fetchone()
        if not row:
            return None
        return MappingEntry(
            ledger_name=ledger_name,
            major_head=row[0],
            sub_head=row[1],
            statement=Statement(row[2]),
            current_or_non_current=CurrentNonCurrent(row[3]),
            nature=Nature(row[4]),
            confidence=0.85,
            source="GLOBAL_LEARNED",
            note_ref=row[5],
        )

    # ------------------------------------------------------------------
    # Writes
    # ------------------------------------------------------------------
    def save_company_mapping(
        self, company_id: int, entry: MappingEntry, user_name: str = "system"
    ) -> None:
        key = normalize(entry.ledger_name)
        with closing(self._connect()) as conn:
            existing = conn.execute(
                "SELECT major_head, sub_head FROM company_mapping WHERE company_id=? AND ledger_key=?",
                (company_id, key),
            ).fetchone()
            conn.execute(
                """
                INSERT INTO company_mapping
                    (company_id, ledger_key, ledger_name, major_head, sub_head, statement,
                     current_or_non_current, nature, note_ref, source, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(company_id, ledger_key) DO UPDATE SET
                    ledger_name=excluded.ledger_name,
                    major_head=excluded.major_head,
                    sub_head=excluded.sub_head,
                    statement=excluded.statement,
                    current_or_non_current=excluded.current_or_non_current,
                    nature=excluded.nature,
                    note_ref=excluded.note_ref,
                    source=excluded.source,
                    updated_at=CURRENT_TIMESTAMP
                """,
                (
                    company_id, key, entry.ledger_name, entry.major_head, entry.sub_head,
                    entry.statement.value, entry.current_or_non_current.value, entry.nature.value,
                    entry.note_ref, entry.source,
                ),
            )
            conn.execute(
                "INSERT INTO audit_log (company_id, ledger_name, action, old_value, new_value, user_name) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (
                    company_id, entry.ledger_name,
                    "REMAPPED" if existing else "MAPPED",
                    f"{existing[0]} / {existing[1]}" if existing else None,
                    f"{entry.major_head} / {entry.sub_head}",
                    user_name,
                ),
            )
            conn.commit()

        # Also reinforce (or seed) the global/learned table so other
        # companies with the same ledger name benefit next time.
        self._upsert_global_mapping(entry)

    def _upsert_global_mapping(self, entry: MappingEntry) -> None:
        key = normalize(entry.ledger_name)
        with closing(self._connect()) as conn:
            conn.execute(
                """
                INSERT INTO global_mapping
                    (ledger_key, ledger_name, major_head, sub_head, statement,
                     current_or_non_current, nature, note_ref, times_confirmed, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1, CURRENT_TIMESTAMP)
                ON CONFLICT(ledger_key) DO UPDATE SET
                    times_confirmed = times_confirmed + 1,
                    major_head=excluded.major_head,
                    sub_head=excluded.sub_head,
                    statement=excluded.statement,
                    current_or_non_current=excluded.current_or_non_current,
                    nature=excluded.nature,
                    note_ref=excluded.note_ref,
                    updated_at=CURRENT_TIMESTAMP
                """,
                (
                    key, entry.ledger_name, entry.major_head, entry.sub_head,
                    entry.statement.value, entry.current_or_non_current.value,
                    entry.nature.value, entry.note_ref,
                ),
            )
            conn.commit()

    def get_audit_log(self, company_id: int, limit: int = 100) -> list[dict]:
        with closing(self._connect()) as conn:
            rows = conn.execute(
                "SELECT ledger_name, action, old_value, new_value, user_name, created_at "
                "FROM audit_log WHERE company_id=? ORDER BY id DESC LIMIT ?",
                (company_id, limit),
            ).fetchall()
        return [
            dict(zip(["ledger_name", "action", "old_value", "new_value", "user_name", "created_at"], r))
            for r in rows
        ]


def resolve_mapping(
    store: MappingStore, company_id: int, ledger_name: str
) -> Optional[MappingEntry]:
    """
    Full resolution order: company override -> global learned -> rule engine.
    Returns None if nothing matches (caller should prompt the user).
    """
    from schedule3_engine.core.classifier import classify_ledger, suggestion_to_mapping_entry

    company_hit = store.get_company_mapping(company_id, ledger_name)
    if company_hit:
        return company_hit

    global_hit = store.get_global_mapping(ledger_name)
    if global_hit:
        return global_hit

    suggestion = classify_ledger(ledger_name)
    return suggestion_to_mapping_entry(suggestion)
