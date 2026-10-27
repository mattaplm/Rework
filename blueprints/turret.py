"""Turret log + entry form (see services/turret.py's docstring). Viewing the
log needs no particular role (same as blueprints/rework.py's log); creating
or editing an entry needs `operator`, same as Doors.
"""

from __future__ import annotations

from flask import Blueprint, abort, jsonify, render_template, request

from services import audit, reference_data, test_data
from services import turret as turret_service
from services.auth import current_user, role_required

bp = Blueprint("turret", __name__)


@bp.route("/turret")
def list_page():
    filters = {
        "year": request.args.get("year") or None,
        "month": request.args.get("month") or None,
        "door_type": request.args.get("door_type") or None,
        "job_number": request.args.get("job_number") or None,
    }
    events = turret_service.list_events(limit=200, filters=filters)

    # Same admin-only visibility as blueprints/rework.py's log -- the fake
    # test SO is for admins testing the entry forms, not something a real
    # operator/viewer should see mixed into their log (2026-10-22).
    user = current_user()
    if not user or user["role"] != "admin":
        events = [e for e in events if not (e.get("sales_number") and e["sales_number"].lower() == test_data.SO_NUMBER.lower())]

    available_weeks = turret_service.list_available_scrap_weeks()
    write_off_week = request.args.get("write_off_week") or None
    write_off_year = request.args.get("write_off_year") or None
    # Only default on a genuinely fresh page load (neither param present at
    # all) -- an explicit "All weeks" choice submits both params empty,
    # which must stay "no filter" -- see blueprints/rework.py's identical note.
    if "write_off_week" not in request.args and "write_off_year" not in request.args and available_weeks:
        write_off_year = str(available_weeks[0]["write_off_year"])
        write_off_week = str(available_weeks[0]["write_off_week"])
    writeoff_rows = turret_service.scrap_summary_by_week(
        int(write_off_week) if write_off_week else None,
        int(write_off_year) if write_off_year else None,
    )
    if not user or user["role"] != "admin":
        writeoff_rows = [r for r in writeoff_rows if not r.get("includes_test_data")]

    return render_template(
        "turret_list.html",
        active="turret",
        events=events,
        filters=filters,
        years=turret_service.list_available_years(),
        door_types=turret_service.list_door_types(),
        writeoff_rows=writeoff_rows,
        write_off_week=write_off_week,
        write_off_year=write_off_year,
        available_weeks=available_weeks,
        test_so_number=test_data.SO_NUMBER,
    )


def _form_context(event: dict | None) -> dict:
    return dict(
        active="turret_new",
        event=event,
        door_types=turret_service.list_door_types(),
        colours=reference_data.list_colours(),
        sheet_items=reference_data.list_sheet_items(),
        reasons=reference_data.list_reasons(),
        rework_types=turret_service.REWORK_TYPES,
        test_so_number=test_data.SO_NUMBER,
    )


@bp.route("/turret/new")
@role_required("operator")
def new_page():
    return render_template("turret_new.html", **_form_context(None))


@bp.route("/turret/<int:event_id>/edit")
@role_required("operator")
def edit_page(event_id: int):
    event = turret_service.get_event(event_id)
    if not event:
        abort(404)
    return render_template("turret_new.html", **_form_context(event))


@bp.route("/api/turret-events", methods=["POST"])
@role_required("operator")
def api_create():
    payload = request.get_json(force=True, silent=True) or {}
    user = current_user()
    try:
        event_id = turret_service.create_event(payload, user_id=user["id"] if user else None)
    except turret_service.ValidationError as exc:
        return jsonify({"ok": False, "errors": exc.errors}), 400
    audit.log(
        user["username"] if user else "unknown", "turret_event.create", "turret_event", event_id,
        {"sales_number": payload.get("sales_number"), "job_number": payload.get("job_number"), "door_type": payload.get("door_type")},
    )
    return jsonify({"ok": True, "id": event_id})


@bp.route("/api/turret-events/<int:event_id>", methods=["POST"])
@role_required("operator")
def api_update(event_id: int):
    payload = request.get_json(force=True, silent=True) or {}
    try:
        turret_service.update_event(event_id, payload)
    except turret_service.ValidationError as exc:
        return jsonify({"ok": False, "errors": exc.errors}), 400
    except ValueError:
        return jsonify({"ok": False, "error": "Turret entry not found."}), 404
    user = current_user()
    audit.log(
        user["username"] if user else "unknown", "turret_event.update", "turret_event", event_id,
        {"rework_type": payload.get("rework_type"), "reason": payload.get("reason")},
    )
    return jsonify({"ok": True})
