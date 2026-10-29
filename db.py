"""
Database layer for the Doors Rework tracker.

Local storage:  PostgreSQL or SQLite (selected by DATABASE_BACKEND)
Remote source:  SyteLine SQL Server (read-only ERP data via pyodbc) -- see erp.py

Raw SQL throughout, no ORM -- same convention as Scheduler's db.py. Every
function takes/returns plain dicts (via RealDictCursor), never a Flask object,
so this module is usable from a script or a test without a request context.
"""

from __future__ import annotations

import logging
import os
from contextlib import contextmanager
from pathlib import Path
from zoneinfo import ZoneInfo
from datetime import datetime, timedelta, timezone

import psycopg2
import psycopg2.extras
import psycopg2.pool
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

_NZ_TZ = ZoneInfo("Pacific/Auckland")

_MIGRATIONS_DIR = Path(__file__).parent / "migrations"


def backend() -> str:
    value = os.getenv("DATABASE_BACKEND", "postgres").lower()
    if value not in ("postgres", "sqlite"):
        raise ValueError("DATABASE_BACKEND must be postgres or sqlite")
    return value


def date_part(part: str, expression: str) -> str:
    if part.lower() not in ("year", "month", "week", "isoyear"):
        raise ValueError("Unsupported date part")
    if backend() == "sqlite":
        return f"date_part('{part.lower()}', {expression})"
    return f"CAST(EXTRACT({part} FROM {expression}) AS INTEGER)"


def week_start(expression: str) -> str:
    if backend() == "sqlite":
        return f"week_start({expression})"
    return f"date_trunc('week', {expression})::date::text"


def date_shift(expression: str, days: int) -> str:
    if backend() == "sqlite":
        return f"date_shift({expression}, {int(days)})"
    return f"(({expression})::date + {int(days)})"


def in_values(expression: str, placeholder: str) -> str:
    if backend() == "sqlite":
        return f"{expression} IN (SELECT value FROM json_each({placeholder}))"
    return f"{expression} = ANY({placeholder})"


def sorted_array(expression: str) -> str:
    if backend() == "sqlite":
        return f"sorted_array({expression})"
    return f"array_agg(DISTINCT {expression} ORDER BY {expression}) FILTER (WHERE {expression} IS NOT NULL)"


def nz_now() -> datetime:
    """Wall-clock 'now' in NZ time, as a naive datetime -- see Scheduler's db.nz_now
    for why (containers default to UTC regardless of where they're hosted)."""
    return datetime.now(_NZ_TZ).replace(tzinfo=None)


def _dsn() -> dict:
    return dict(
        host=os.getenv("POSTGRES_HOST", "localhost"),
        port=os.getenv("POSTGRES_PORT", "5432"),
        dbname=os.getenv("POSTGRES_DB", "rework"),
        user=os.getenv("POSTGRES_USER", "rework"),
        password=os.getenv("POSTGRES_PASSWORD", ""),
    )


_pool: psycopg2.pool.ThreadedConnectionPool | None = None


def _get_pool() -> psycopg2.pool.ThreadedConnectionPool:
    """Every previous version of this function opened a brand-new TCP +
    Postgres connection per call (every page load fired off half a dozen of
    these back to back -- e.g. login alone is 4 separate round trips), which
    is the main reason the app felt slow. One pooled connection per request
    instead, reused across requests."""
    global _pool
    if _pool is None:
        _pool = psycopg2.pool.ThreadedConnectionPool(
            1, 5, cursor_factory=psycopg2.extras.RealDictCursor, **_dsn()
        )
    return _pool


@contextmanager
def get_conn():
    """Commit on success and roll back on failure. Close SQLite connections;
    return PostgreSQL connections to the pool."""
    sqlite = backend() == "sqlite"
    if sqlite:
        from sqlite_db import Connection
        conn = Connection(os.getenv("SQLITE_PATH", "data/rework.sqlite3"))
    else:
        pool = _get_pool()
        conn = pool.getconn()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        if sqlite:
            conn.close()
        else:
            pool.putconn(conn)


def init_db() -> None:
    """Runs every migrations/*.sql file in order, inside its own transaction,
    tracked in a schema_migrations table so each file only ever runs once.
    Safe to call on every startup."""
    if backend() == "sqlite":
        _init_sqlite()
        _ensure_default_admin()
        return
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "CREATE TABLE IF NOT EXISTS schema_migrations ("
                "  filename TEXT PRIMARY KEY, applied_at TIMESTAMPTZ NOT NULL DEFAULT now()"
                ")"
            )
            cur.execute("SELECT filename FROM schema_migrations")
            applied = {row["filename"] for row in cur.fetchall()}

        for path in sorted(_MIGRATIONS_DIR.glob("*.sql")):
            if path.name in applied:
                continue
            logger.info("Applying migration %s", path.name)
            with conn.cursor() as cur:
                cur.execute(path.read_text())
                cur.execute("INSERT INTO schema_migrations (filename) VALUES (%s)", (path.name,))

    _ensure_default_admin()


def _init_sqlite() -> None:
    import sqlite3
    with get_conn() as conn:
        conn.raw.execute("PRAGMA journal_mode=WAL")
        conn.raw.execute(
            "CREATE TABLE IF NOT EXISTS schema_migrations "
            "(filename TEXT PRIMARY KEY, applied_at TEXT NOT NULL DEFAULT (now()))"
        )
        applied = {row["filename"] for row in conn.raw.execute("SELECT filename FROM schema_migrations")}
        for path in sorted((_MIGRATIONS_DIR / "sqlite").glob("*.sql")):
            if path.name in applied:
                continue
            logger.info("Applying SQLite migration %s", path.name)
            conn.raw.execute("BEGIN IMMEDIATE")
            # executescript commits an open transaction implicitly. Execute
            # complete statements separately to keep schema+version atomic.
            statement = ""
            for line in path.read_text(encoding="utf-8").splitlines(keepends=True):
                statement += line
                if sqlite3.complete_statement(statement):
                    conn.raw.execute(statement)
                    statement = ""
            if statement.strip():
                raise ValueError(f"Incomplete SQLite migration: {path.name}")
            conn.raw.execute("INSERT INTO schema_migrations (filename) VALUES (?)", (path.name,))
            conn.commit()


def _ensure_default_admin() -> None:
    from werkzeug.security import generate_password_hash
    import secrets

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) AS n FROM users")
            if cur.fetchone()["n"]:
                return
            # 4-digit PIN auth (2026-10-22) -- ADMIN_DEFAULT_PASSWORD can
            # still override this (e.g. for a known first PIN), but the
            # generated fallback is now a PIN-shaped value, not a long
            # random password string, matching the policy everywhere else.
            password = os.getenv("ADMIN_DEFAULT_PASSWORD") or f"{secrets.randbelow(10000):04d}"
            cur.execute(
                "INSERT INTO users (username, password_hash, role, active, must_change_password) "
                "VALUES (%s, %s, 'admin', TRUE, TRUE)",
                ("admin", generate_password_hash(password)),
            )
    logger.warning(
        "No users existed -- created default admin account. username=admin PIN=%s "
        "(you will be asked to change it on first login)", password,
    )


# ── Users ─────────────────────────────────────────────────────────────────

def get_user_by_username(username: str) -> dict | None:
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("SELECT * FROM users WHERE username = %s", (username,))
        return cur.fetchone()


def get_user(user_id: int) -> dict | None:
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("SELECT * FROM users WHERE id = %s", (user_id,))
        return cur.fetchone()


def list_users() -> list[dict]:
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("SELECT id, username, role, active, must_change_password, created_at, last_login_at "
                     "FROM users ORDER BY username")
        return cur.fetchall()


def create_user(username: str, password_hash: str | None, role: str = "viewer", must_change: bool = True) -> int:
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            "INSERT INTO users (username, password_hash, role, must_change_password) "
            "VALUES (%s, %s, %s, %s) RETURNING id",
            (username, password_hash, role, must_change),
        )
        return cur.fetchone()["id"]


def set_user_role(user_id: int, role: str) -> None:
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("UPDATE users SET role = %s WHERE id = %s", (role, user_id))


def set_user_active(user_id: int, active: bool) -> None:
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("UPDATE users SET active = %s WHERE id = %s", (active, user_id))


def set_user_password(user_id: int, password_hash: str, must_change: bool = False) -> None:
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            "UPDATE users SET password_hash = %s, must_change_password = %s WHERE id = %s",
            (password_hash, must_change, user_id),
        )


def touch_last_login(user_id: int) -> None:
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("UPDATE users SET last_login_at = now() WHERE id = %s", (user_id,))


# ── Sessions ──────────────────────────────────────────────────────────────

def create_session(sid: str, user_id: int, username: str, role: str, ip: str, user_agent: str) -> None:
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            "INSERT INTO sessions (sid, user_id, username, role, ip, user_agent) "
            "VALUES (%s, %s, %s, %s, %s, %s)",
            (sid, user_id, username, role, ip, user_agent),
        )


def get_session(sid: str) -> dict | None:
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("SELECT * FROM sessions WHERE sid = %s", (sid,))
        return cur.fetchone()


def touch_session(sid: str) -> None:
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("UPDATE sessions SET last_seen_at = now() WHERE sid = %s", (sid,))


def delete_session(sid: str) -> None:
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("DELETE FROM sessions WHERE sid = %s", (sid,))


def delete_user(user_id: int) -> None:
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("DELETE FROM users WHERE id = %s", (user_id,))


def delete_user_sessions(user_id: int) -> None:
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("DELETE FROM sessions WHERE user_id = %s", (user_id,))


def update_sessions_role(user_id: int, role: str) -> None:
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("UPDATE sessions SET role = %s WHERE user_id = %s", (role, user_id))


def list_active_sessions(minutes: int = 15) -> list[dict]:
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT * FROM sessions WHERE last_seen_at > %s "
            "ORDER BY last_seen_at DESC",
            (datetime.now(timezone.utc) - timedelta(minutes=minutes),),
        )
        return cur.fetchall()


def prune_old_sessions(days: int = 30) -> None:
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("DELETE FROM sessions WHERE last_seen_at < %s", (datetime.now(timezone.utc) - timedelta(days=days),))
