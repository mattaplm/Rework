"""Append-only audit trail -- every logon, entry, and modification, by
username (requested 2026-10-22, "do full logging of entries and
modifications and logons by username"). Browsable at Admin -> Audit Log
(`list_recent`); the raw table is `audit_log` (migration 0014).

Deliberately called from the blueprint layer, never from services/*.py:
"who did this" is a web-session concept (`services.auth.current_user()`),
and keeping it out of the framework-agnostic service layer matches this
app's existing services/blueprints split (see CLAUDE.md, "Layering") --
every mutating route calls `audit.log(...)` itself, right after its own
service call succeeds, instead of every service function growing a
`username` parameter it has no other use for.

`detail` is a plain JSON-encoded string, not a native Postgre JSONB column
-- this project hasn't used jsonb anywhere else, and a plain TEXT column
sidesteps any question of whether PGlite's jsonb support is complete for
local dev. Callers pass a plain dict; this module handles the
serialisation both ways.
"""

from __future__ import annotations

import json

import db


def log(username: str, action: str, entity_type: str | None = None, entity_id=None, detail: dict | None = None) -> None:
    with db.get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            "INSERT INTO audit_log (username, action, entity_type, entity_id, detail) VALUES (%s, %s, %s, %s, %s)",
            (
                username, action, entity_type,
                str(entity_id) if entity_id is not None else None,
                json.dumps(detail) if detail is not None else None,
            ),
        )


def list_recent(limit: int = 200) -> list[dict]:
    """Shown at Admin -> Audit Log. `at` is formatted here (local server
    time) rather than left for the template, same convention as
    admin_data._fmt_synced_at -- a TIMESTAMPTZ's default str() includes
    microseconds and a numeric UTC offset, not fit for a glance at a log."""
    with db.get_conn() as conn, conn.cursor() as cur:
        cur.execute("SELECT * FROM audit_log ORDER BY at DESC LIMIT %s", (limit,))
        rows = cur.fetchall()
    for row in rows:
        row["detail"] = json.loads(row["detail"]) if row["detail"] else None
        row["at"] = row["at"].astimezone().strftime("%Y-%m-%d %H:%M:%S")
    return rows
