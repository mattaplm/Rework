"""Hardware department: PC log, entry form, and Hardware Admin (2026-11-11).
See services/hardware.py for what the log is and how it's costed."""

from __future__ import annotations

import logging

from flask import Blueprint, jsonify, redirect, render_template, request, url_for

from services import admin_data, audit
from services import hardware as hw
from services import hardware_admin
from services.auth import current_user, login_required, role_required

logger = logging.getLogger(__name__)
bp = Blueprint("hardware", __name__)


def _actor() -> str:
    user = current_user()
    return user["username"] if user else "unknown"


@bp.route("/hardware")
@login_required
def home():
    return redirect(url_for("hardware.log_page"))


@bp.route("/hardware/log")
@login_required
def log_page():
    filters = {key: (request.args.get(key) or "").strip() or None for key in hw.FILTER_KEYS}
    return render_template(
        "hw_log.html",
        active="hw_log",
        events=hw.list_events(filters),
        totals=hw.summary(filters),
        filters=filters,
        limit=hw.LOG_LIMIT,
        years=hw.list_years(),
        reasons=hw.list_used_reasons(),
        statuses=hw.STATUSES,
        locations=hw.LOCATIONS,
    )


def _form_page(event: dict | None):
    return render_template(
        "hw_new.html",
        active="hw_new" if event is None else "hw_log",
        event=hw.event_json(event) if event else None,
        today=hw._today().isoformat(),
        reasons=[{"reason": r["reason"], "is_scrap": bool(r["is_scrap"])} for r in hw.list_reasons()],
        parts=hw.list_parts(),
        colours=hw.list_colours(),
        powdercoaters=hw.list_names("powdercoater"),
        assemblers=hw.list_names("assembler"),
        locations=hw.LOCATIONS,
    )


@bp.route("/hardware/new")
@role_required("operator")
def new_page():
    return _form_page(None)


@bp.route("/hardware/<int:event_id>/edit")
@role_required("operator")
def edit_page(event_id: int):
    event = hw.get_event(event_id)
    if event is None:
        return redirect(url_for("hardware.log_page"))
    return _form_page(event)


@bp.route("/api/hardware/events", methods=["POST"])
@role_required("operator")
def api_create():
    payload = request.get_json(force=True, silent=True) or {}
    user = current_user()
    try:
        event = hw.create_event(payload, user["id"] if user else None)
    except hw.ValidationError as exc:
        return jsonify({"ok": False, "errors": exc.errors}), 400
    audit.log(_actor(), "hw_event.create", "hw_event", event["id"],
              {"part_number": event["part_number"], "quantity": event["quantity"], "reason": event["reason"]})
    return jsonify({"ok": True, "event": hw.event_json(event)})


@bp.route("/api/hardware/events/<int:event_id>", methods=["POST"])
@role_required("operator")
def api_update(event_id: int):
    payload = request.get_json(force=True, silent=True) or {}
    try:
        event = hw.update_event(event_id, payload)
    except LookupError:
        return jsonify({"ok": False, "error": "Entry not found"}), 404
    except hw.ValidationError as exc:
        return jsonify({"ok": False, "errors": exc.errors}), 400
    audit.log(_actor(), "hw_event.update", "hw_event", event_id,
              {"status": event["status"], "part_number": event["part_number"], "quantity": event["quantity"]})
    return jsonify({"ok": True, "event": hw.event_json(event)})


# ── Hardware Admin ──────────────────────────────────────────────────────────

@bp.route("/hardware/admin")
@role_required("admin")
def admin_page():
    return render_template(
        "hw_admin.html",
        active="hw_admin",
        reasons=hw.list_reasons(active_only=False),
        parts=hw.list_parts(active_only=False),
        powdercoaters=admin_data.list_named_all("hw_powdercoaters"),
        assemblers=admin_data.list_named_all("hw_assemblers"),
    )


def _bool(value) -> bool:
    return value in (True, "true", "on", "1", 1, "yes")


@bp.route("/api/hardware/admin/reasons", methods=["POST"])
@role_required("admin")
def api_create_reason():
    data = request.get_json(force=True, silent=True) or {}
    reason = str(data.get("reason") or "").strip()
    if not reason:
        return jsonify({"ok": False, "error": "Reason is required"}), 400
    try:
        hardware_admin.create_reason(reason, _bool(data.get("is_scrap")))
    except Exception as exc:
        return jsonify({"ok": False, "error": f"Couldn't add it -- is it already listed? ({exc})"}), 400
    audit.log(_actor(), "hw_reason.create", "hw_reason", reason, {"is_scrap": _bool(data.get("is_scrap"))})
    return jsonify({"ok": True})


@bp.route("/api/hardware/admin/reasons/<int:reason_id>", methods=["POST"])
@role_required("admin")
def api_save_reason(reason_id: int):
    data = request.get_json(force=True, silent=True) or {}
    reason = str(data.get("reason") or "").strip()
    if not reason:
        return jsonify({"ok": False, "error": "Reason is required"}), 400
    try:
        sort_order = int(data.get("sort_order"))
    except (TypeError, ValueError):
        return jsonify({"ok": False, "error": "Sort order must be a whole number"}), 400
    try:
        updated = hardware_admin.save_reason(reason_id, reason, _bool(data.get("is_scrap")), sort_order)
    except Exception as exc:
        logger.exception("Saving hardware reason %s failed", reason_id)
        return jsonify({"ok": False, "error": str(exc)}), 400
    audit.log(_actor(), "hw_reason.save", "hw_reason", reason_id,
              {"reason": reason, "is_scrap": _bool(data.get("is_scrap")), "sort_order": sort_order})
    return jsonify({"ok": True, "updated_historical_rows": updated})


@bp.route("/api/hardware/admin/reasons/<int:reason_id>/active", methods=["POST"])
@role_required("admin")
def api_reason_active(reason_id: int):
    active = _bool((request.get_json(force=True, silent=True) or {}).get("active", True))
    hardware_admin.set_reason_active(reason_id, active)
    audit.log(_actor(), "hw_reason.set_active", "hw_reason", reason_id, {"active": active})
    return jsonify({"ok": True})


@bp.route("/api/hardware/admin/parts", methods=["POST"])
@role_required("admin")
def api_save_part():
    data = request.get_json(force=True, silent=True) or {}
    try:
        hardware_admin.save_part(data.get("old_part_number"), data)
    except ValueError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400
    audit.log(_actor(), "hw_part.save", "hw_part", str(data.get("part_number") or "").strip().upper(),
              {k: data.get(k) for k in ("old_part_number", "unit_cost", "material_cost", "supplier",
                                        "product_code", "material")})
    return jsonify({"ok": True})


@bp.route("/api/hardware/admin/parts/<path:part_number>/active", methods=["POST"])
@role_required("admin")
def api_part_active(part_number: str):
    active = _bool((request.get_json(force=True, silent=True) or {}).get("active", True))
    hardware_admin.set_part_active(part_number, active)
    audit.log(_actor(), "hw_part.set_active", "hw_part", part_number, {"active": active})
    return jsonify({"ok": True})
