from __future__ import annotations

from flask import Blueprint, redirect, url_for

bp = Blueprint("pages", __name__)


@bp.route("/")
def index():
    return redirect(url_for("rework.list_page"))
