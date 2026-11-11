from __future__ import annotations

from flask import Blueprint, render_template

from services.auth import login_required

bp = Blueprint("pages", __name__)


@bp.route("/")
@login_required
def index():
    """Department picker (Doors / Hardware), same idea as Scheduler's landing
    page. Logging in lands here."""
    return render_template("landing.html")
