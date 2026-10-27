"""Login/session helpers and role-gate decorators.

Direct port of Scheduler's services/auth.py onto Postgres -- same server-side
session tracking (so a role change or deactivation takes effect immediately,
not on next login), same hierarchical viewer < operator < admin roles.
"""

from __future__ import annotations

import re
import uuid
from functools import wraps

from flask import g, jsonify, redirect, render_template, request, session, url_for

import db

ROLES     = ("viewer", "operator", "admin")
ROLE_RANK = {role: i for i, role in enumerate(ROLES)}

_PIN_RE = re.compile(r"^\d{4}$")


def is_valid_pin(value: str) -> bool:
    """4-digit PIN auth (replaced free-text passwords 2026-10-22) -- exactly
    4 digits, nothing else. Viewer accounts don't need one at all (see
    `can_login_without_pin`); every other role must have one."""
    return bool(_PIN_RE.fullmatch(value or ""))


def can_login_without_pin(user: dict) -> bool:
    """Viewer accounts with no PIN set log in on username alone -- the
    login form still has a PIN field (shared with operator/admin), but
    whatever's typed there is ignored for this case. Anything stored in
    `password_hash` means a PIN was deliberately set, so it's still
    checked normally even for a viewer (an admin can still give a viewer a
    real PIN via Reset Password if they want one)."""
    return user["role"] == "viewer" and user["password_hash"] is None


def login_user(user: dict) -> None:
    sid = uuid.uuid4().hex
    session.clear()
    session["sid"] = sid
    session.permanent = True
    db.create_session(
        sid, user["id"], user["username"], user["role"],
        request.remote_addr, request.headers.get("User-Agent", "")[:255],
    )
    db.touch_last_login(user["id"])
    db.prune_old_sessions()


def logout_user() -> None:
    sid = session.get("sid")
    if sid:
        db.delete_session(sid)
    session.clear()


def current_user() -> dict | None:
    sid = session.get("sid")
    if not sid:
        return None
    if not hasattr(g, "_current_user"):
        row = db.get_session(sid)
        if row is None:
            session.clear()
            g._current_user = None
        else:
            g._current_user = {"id": row["user_id"], "username": row["username"], "role": row["role"], "sid": sid}
    return g._current_user


def touch_current_session() -> None:
    """Bumps last_seen_at for the caller's session -- called once per request from app.py."""
    sid = session.get("sid")
    if sid:
        db.touch_session(sid)


def _unauthorized():
    if request.path.startswith("/api/"):
        return jsonify({"ok": False, "error": "Login required"}), 401
    return redirect(url_for("auth.login_page", next=request.path))


def _forbidden(min_role: str):
    message = f"Requires {min_role} role"
    if request.path.startswith("/api/"):
        return jsonify({"ok": False, "error": message}), 403
    return render_template("403.html", message=message), 403


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if current_user() is None:
            return _unauthorized()
        return view(*args, **kwargs)
    return wrapped


def role_required(min_role: str):
    """Require the caller to be logged in with at least `min_role` (viewer < operator < admin)."""
    def decorator(view):
        @wraps(view)
        def wrapped(*args, **kwargs):
            user = current_user()
            if user is None:
                return _unauthorized()
            if ROLE_RANK.get(user["role"], -1) < ROLE_RANK[min_role]:
                return _forbidden(min_role)
            return view(*args, **kwargs)
        return wrapped
    return decorator
