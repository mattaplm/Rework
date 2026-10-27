from __future__ import annotations

from flask import Blueprint, render_template, request

from services import reporting
from services.auth import login_required

bp = Blueprint("dashboard", __name__)


@bp.route("/dashboard")
@login_required
def dashboard_page():
    days_param = request.args.get("days", "90")
    days = None if days_param == "all" else int(days_param)
    weeks = None if days is None else max(12, days // 7)
    return render_template(
        "dashboard.html",
        active="dashboard",
        days=days_param,
        summary=reporting.summary(days),
        weekly_trend=reporting.weekly_trend(weeks=weeks),
        top_reasons=reporting.top_reasons(days=days),
        by_door_type=reporting.by_door_type(days=days),
        by_colour=reporting.by_colour(days=days),
    )
