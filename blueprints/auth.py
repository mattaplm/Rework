from __future__ import annotations

from flask import Blueprint, redirect, render_template, request, url_for
from werkzeug.security import check_password_hash, generate_password_hash

import db
from services import audit
from services import auth as auth_service

bp = Blueprint("auth", __name__)


def _active_usernames() -> list[str]:
    """Login page shows a username picker instead of a free-text field
    (requested 2026-10-22, "trying to avoid people forgetting their
    username") -- active accounts only, since a deactivated one can't log
    in regardless of what's picked."""
    return [u["username"] for u in db.list_users() if u["active"]]


@bp.route("/login", methods=["GET", "POST"])
def login_page():
    if request.method == "GET":
        if auth_service.current_user():
            return redirect(url_for("dashboard.dashboard_page"))
        return render_template("login.html", error=None, usernames=_active_usernames())

    username = request.form.get("username", "").strip()
    password = request.form.get("password", "")
    user = db.get_user_by_username(username)

    if not user or not user["active"]:
        return render_template("login.html", error="Incorrect username or PIN.", usernames=_active_usernames(), selected_username=username), 401
    # Viewer accounts with no PIN set log in on username alone -- whatever
    # was typed in the PIN field (even nothing) is ignored for this case.
    # Every other account still needs a correct PIN.
    if not auth_service.can_login_without_pin(user):
        if not user["password_hash"] or not check_password_hash(user["password_hash"], password):
            return render_template("login.html", error="Incorrect username or PIN.", usernames=_active_usernames(), selected_username=username), 401

    auth_service.login_user(user)
    audit.log(user["username"], "login")
    if user["must_change_password"]:
        return redirect(url_for("auth.change_password_page"))
    return redirect(request.args.get("next") or url_for("dashboard.dashboard_page"))


@bp.route("/logout", methods=["POST"])
def logout():
    auth_service.logout_user()
    return redirect(url_for("auth.login_page"))


@bp.route("/change-password", methods=["GET", "POST"])
@auth_service.login_required
def change_password_page():
    if request.method == "GET":
        return render_template("change_password.html", error=None)

    new_password = request.form.get("new_password", "")
    confirm = request.form.get("confirm", "")
    if not auth_service.is_valid_pin(new_password):
        return render_template("change_password.html", error="PIN must be exactly 4 digits."), 400
    if new_password != confirm:
        return render_template("change_password.html", error="PINs don't match."), 400

    user = auth_service.current_user()
    db.set_user_password(user["id"], generate_password_hash(new_password), must_change=False)
    audit.log(user["username"], "change_password", "user", user["id"])
    return redirect(url_for("dashboard.dashboard_page"))
