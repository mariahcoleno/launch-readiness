"""SQLite connection and schema setup."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Union

SCHEMA_PATH = Path(__file__).with_name("schema.sql")


def get_connection(path: Union[str, Path]) -> sqlite3.Connection:
    """Open a connection with foreign keys on and rows readable by column name."""
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    """Create tables if they don't exist. Safe to run more than once."""
    conn.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
    conn.commit()
