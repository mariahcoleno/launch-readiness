"""SQLite connection and schema setup."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Union

SCHEMA_PATH = Path(__file__).with_name("schema.sql")

# Bump this whenever schema.sql changes in a way old databases don't have.
# 2: gates.waived_by, and the waiver rule on gates.
SCHEMA_VERSION = 2

TABLES_CHILD_FIRST = ("decisions", "gates", "launch_features", "launches")


def get_connection(path: Union[str, Path]) -> sqlite3.Connection:
    """Open a connection with foreign keys on and rows readable by column name."""
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def _has_tables(conn: sqlite3.Connection) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'launches'"
    ).fetchone()
    return row is not None


def init_db(conn: sqlite3.Connection) -> None:
    """Create tables if they don't exist. Safe to run more than once.

    Only a brand-new database is stamped with the current schema version, so an
    older database keeps its old version and schema_is_current() can spot it.
    """
    is_new = not _has_tables(conn)
    conn.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
    if is_new:
        conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
    conn.commit()


def schema_is_current(conn: sqlite3.Connection) -> bool:
    return conn.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION


def reset_db(conn: sqlite3.Connection) -> None:
    """Delete every table and recreate them empty, at the current schema version."""
    for table in TABLES_CHILD_FIRST:
        conn.execute(f"DROP TABLE IF EXISTS {table}")
    conn.execute("PRAGMA user_version = 0")
    conn.commit()
    init_db(conn)
