"""The SQLite schema creates cleanly and enforces its basic rules."""

import sqlite3

import pytest

from launch_readiness.db import get_connection, init_db


@pytest.fixture
def conn(tmp_path):
    c = get_connection(tmp_path / "test.db")
    init_db(c)
    yield c
    c.close()


@pytest.fixture
def launch_id(conn):
    cur = conn.execute(
        "INSERT INTO launches (name, model_version, stage) VALUES (?, ?, ?)",
        ("Model Atlas v2.1", "v2.1", "trusted_testers"),
    )
    return cur.lastrowid


def add_gate(conn, launch_id, key="safety_evals", status="not_started"):
    conn.execute(
        "INSERT INTO gates (launch_id, gate_key, name, team, status) VALUES (?, ?, ?, ?, ?)",
        (launch_id, key, "Safety evals", "Safety", status),
    )


def test_tables_created(conn):
    names = {r["name"] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"launches", "launch_features", "gates", "decisions"} <= names


def test_init_db_is_safe_to_run_twice(conn):
    init_db(conn)


def test_gate_defaults_to_not_started_and_not_removed(conn, launch_id):
    add_gate(conn, launch_id)
    row = conn.execute("SELECT status, removed_at FROM gates").fetchone()
    assert row["status"] == "not_started"
    assert row["removed_at"] is None


def test_bad_gate_status_rejected(conn, launch_id):
    with pytest.raises(sqlite3.IntegrityError):
        add_gate(conn, launch_id, status="done")


def test_same_gate_twice_per_launch_rejected(conn, launch_id):
    add_gate(conn, launch_id)
    with pytest.raises(sqlite3.IntegrityError):
        add_gate(conn, launch_id)


def test_bad_stage_rejected(conn):
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO launches (name, model_version, stage) VALUES ('x', 'v', 'beta')"
        )


def test_bad_feature_name_rejected(conn, launch_id):
    conn.execute(
        "INSERT INTO launch_features VALUES (?, 'capability', 'code_execution')", (launch_id,)
    )
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO launch_features VALUES (?, 'capability', 'enterprise')", (launch_id,)
        )


def test_decision_needs_rationale(conn, launch_id):
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO decisions (launch_id, kind, decided_by, decided_on, rationale) "
            "VALUES (?, 'go', 'Priya N.', '2026-10-21', '  ')",
            (launch_id,),
        )


def test_gate_for_missing_launch_rejected(conn):
    with pytest.raises(sqlite3.IntegrityError):
        add_gate(conn, 999)


# --- Schema version -----------------------------------------------------------

from launch_readiness.db import SCHEMA_VERSION, reset_db, schema_is_current  # noqa: E402


def test_new_database_is_current(conn):
    assert schema_is_current(conn)
    assert conn.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION


def test_older_database_is_spotted_and_not_restamped(conn):
    conn.execute("PRAGMA user_version = 1")
    init_db(conn)  # what the app does on start
    assert not schema_is_current(conn)


def test_reset_makes_an_older_database_current_and_empty(conn, launch_id):
    conn.execute("PRAGMA user_version = 1")
    reset_db(conn)
    assert schema_is_current(conn)
    assert conn.execute("SELECT COUNT(*) FROM launches").fetchone()[0] == 0


def test_app_explains_an_older_database(tmp_path):
    from launch_readiness.app import create_app

    path = tmp_path / "old.db"
    old = get_connection(path)
    init_db(old)
    old.execute("PRAGMA user_version = 1")
    old.close()

    client = create_app({"TESTING": True, "DATABASE": str(path)}).test_client()
    response = client.get("/")
    assert response.status_code == 503
    assert "older version of the app" in response.get_data(as_text=True)
    assert "flask --app launch_readiness.app seed" in response.get_data(as_text=True)
    assert client.get("/static/style.css").status_code == 200
