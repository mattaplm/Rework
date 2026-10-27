"""Read-only connection to the SyteLine ERP reports DB (`alpac_App`), same
server Scheduler connects to. Separate from db.py (which only ever talks to
this app's own Postgres) -- same local/remote split as Scheduler's db.py vs.
its SQL Server bits, just in two files instead of one.
"""

from __future__ import annotations

import os
from contextlib import contextmanager

import pyodbc
from dotenv import load_dotenv

load_dotenv()


class ErpNotConfigured(Exception):
    """Raised when SQL_SERVER/SQL_DATABASE aren't set -- sync is an opt-in
    feature, not a hard requirement to run the app (see CLAUDE.md)."""


def _conn_str() -> str:
    server = os.getenv("SQL_SERVER", "")
    database = os.getenv("SQL_DATABASE", "")
    if not server or not database:
        raise ErpNotConfigured("SQL_SERVER / SQL_DATABASE are not set")
    return (
        f"DRIVER={os.getenv('SQL_DRIVER', '{ODBC Driver 17 for SQL Server}')};"
        f"SERVER={server};DATABASE={database};"
        f"UID={os.getenv('SQL_USERNAME', '')};PWD={os.getenv('SQL_PASSWORD', '')};"
    )


@contextmanager
def get_conn():
    conn = pyodbc.connect(_conn_str(), timeout=15)
    try:
        yield conn
    finally:
        conn.close()


def test_connection() -> tuple[bool, str]:
    """Returns (ok, message) -- never raises, so the Admin page can show a
    friendly status instead of a stack trace."""
    try:
        with get_conn() as conn:
            conn.cursor().execute("SELECT 1")
        return True, "Connected"
    except ErpNotConfigured as exc:
        return False, str(exc)
    except Exception as exc:  # pyodbc.Error and friends -- report, don't crash the page
        return False, str(exc)


def fetch_all(query: str, params: tuple = ()) -> list[dict]:
    """Runs `query` and returns every row as a plain dict (column name -> value).
    `params` binds to `?` placeholders -- required for any query built from
    user input (e.g. an SO number typed into the entry form), never string-
    interpolated, same as every parameterized call elsewhere in this app."""
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute(query, params) if params else cur.execute(query)
        columns = [c[0] for c in cur.description]
        return [dict(zip(columns, row)) for row in cur.fetchall()]
