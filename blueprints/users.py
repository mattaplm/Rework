"""API -- user management (Admin only). Direct port of Scheduler's
blueprints/users.py onto this app's db.py."""

from __future__ import annotations

import logging

from flask import Blueprint, jsonify, request
from werkzeug.security import generate_password_hash

import db
from services import audit
from services.auth import ROLES, current_user, is_valid_pin, role_required

logger = logging.getLogger(__name__)

bp = Blueprint("users", __name__, url_prefix="/api/users")


def _public(user: dict) -> dict:
    return {
        "id": user["id"],
        "username": user["username"],
        "role": user["role"],
        "active": bool(user["active"]),
        "must_change_password": bool(user["must_change_password"]),
        "created_at": user.get("created_at"),
        "last_login_at": user.get("last_login_at"),
    }


@bp.route("")
@role_required("admin")
def list_users():
    return jsonify({"ok": True, "users": [_public(u) for u in db.list_users()]})


@bp.route("", methods=["POST"])
@role_required("admin")
def create_user():
    """4-digit PIN auth (2026-10-22): viewer accounts don't need one at all
    -- an empty password is only valid for role='viewer', stored as a NULL
    password_hash (services.auth.can_login_without_pin treats that as "log
    in on username alone"). Every other role still needs a real 4-digit
    PIN."""
    data = request.get_json(force=True, silent=True) or {}
    username = str(data.get("username", "")).strip()
    password = str(data.get("password", ""))
    role = str(data.get("role", "viewer"))

    if not username:
        return jsonify({"ok": False, "error": "Username is required"}), 400
    if role not in ROLES:
        return jsonify({"ok": False, "error": f"Role must be one of {ROLES}"}), 400
    if role == "viewer" and not password:
        password_hash, must_change = None, False
    elif is_valid_pin(password):
        password_hash, must_change = generate_password_hash(password), True
    else:
        return jsonify({"ok": False, "error": "PIN must be exactly 4 digits (viewer accounts may leave it blank)"}), 400
    if db.get_user_by_username(username):
        return jsonify({"ok": False, "error": "Username already exists"}), 400

    user_id = db.create_user(username, password_hash, role, must_change=must_change)
    logger.info("%s created account %s (role=%s)", current_user()["username"], username, role)
    audit.log(current_user()["username"], "user.create", "user", user_id, {"username": username, "role": role})
    return jsonify({"ok": True, "id": user_id})


@bp.route("/<int:user_id>/role", methods=["POST"])
@role_required("admin")
def set_role(user_id: int):
    role = str((request.get_json(force=True, silent=True) or {}).get("role", ""))
    if role not in ROLES:
        return jsonify({"ok": False, "error": f"Role must be one of {ROLES}"}), 400
    db.set_user_role(user_id, role)
    db.update_sessions_role(user_id, role)
    logger.info("%s set role=%s for user_id=%s", current_user()["username"], role, user_id)
    audit.log(current_user()["username"], "user.set_role", "user", user_id, {"role": role})
    return jsonify({"ok": True})


@bp.route("/<int:user_id>/active", methods=["POST"])
@role_required("admin")
def set_active(user_id: int):
    if user_id == current_user()["id"]:
        return jsonify({"ok": False, "error": "Cannot deactivate your own account"}), 400
    active = bool((request.get_json(force=True, silent=True) or {}).get("active", True))
    db.set_user_active(user_id, active)
    if not active:
        db.delete_user_sessions(user_id)
    logger.info("%s set active=%s for user_id=%s", current_user()["username"], active, user_id)
    audit.log(current_user()["username"], "user.set_active", "user", user_id, {"active": active})
    return jsonify({"ok": True})


@bp.route("/<int:user_id>/reset-password", methods=["POST"])
@role_required("admin")
def reset_password(user_id: int):
    """Same viewer-may-leave-it-blank rule as create_user above -- a blank
    PIN is only valid for a viewer account, clearing password_hash back to
    NULL (logging in on username alone again)."""
    target = db.get_user(user_id)
    if target is None:
        return jsonify({"ok": False, "error": "User not found"}), 404
    password = str((request.get_json(force=True, silent=True) or {}).get("password", ""))
    if target["role"] == "viewer" and not password:
        password_hash, must_change = None, False
    elif is_valid_pin(password):
        password_hash, must_change = generate_password_hash(password), True
    else:
        return jsonify({"ok": False, "error": "PIN must be exactly 4 digits (viewer accounts may leave it blank)"}), 400
    db.set_user_password(user_id, password_hash, must_change=must_change)
    db.delete_user_sessions(user_id)
    logger.info("%s reset password for user_id=%s", current_user()["username"], user_id)
    audit.log(current_user()["username"], "user.reset_password", "user", user_id)
    return jsonify({"ok": True})


@bp.route("/<int:user_id>", methods=["DELETE"])
@role_required("admin")
def delete_user(user_id: int):
    if user_id == current_user()["id"]:
        return jsonify({"ok": False, "error": "Cannot delete your own account"}), 400
    db.delete_user(user_id)
    db.delete_user_sessions(user_id)
    logger.info("%s deleted user_id=%s", current_user()["username"], user_id)
    audit.log(current_user()["username"], "user.delete", "user", user_id)
    return jsonify({"ok": True})


@bp.route("/<int:user_id>/logout", methods=["POST"])
@role_required("admin")
def force_logout(user_id: int):
    db.delete_user_sessions(user_id)
    logger.info("%s force-logged-out user_id=%s", current_user()["username"], user_id)
    audit.log(current_user()["username"], "user.force_logout", "user", user_id)
    return jsonify({"ok": True})


@bp.route("/sessions")
@role_required("admin")
def active_sessions():
    return jsonify({"ok": True, "sessions": db.list_active_sessions()})
