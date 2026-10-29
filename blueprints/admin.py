"""Admin page: SQL/ERP connection, reference-data CRUD (reasons/door codes/
work centres/colours/items). User management lives in blueprints/users.py
(its own API, same split as Scheduler)."""

from __future__ import annotations

import logging

from flask import Blueprint, jsonify, render_template, request

import db
import erp
from services import admin_data, audit, erp_lookup, erp_sync, scheduled_sync, test_data, version
from services.auth import current_user, role_required

logger = logging.getLogger(__name__)

bp = Blueprint("admin", __name__)


def _actor() -> str:
    """Every route in this file is already @role_required("admin"), so
    current_user() is never None here -- a short helper so each audit.log
    call site doesn't repeat current_user()["username"]."""
    return current_user()["username"]


@bp.route("/admin")
@role_required("admin")
def admin_page():
    return render_template(
        "admin.html",
        active="admin",
        reasons=admin_data.list_reasons_all(),
        work_centres=admin_data.list_named_all("work_centres"),
        colours=admin_data.list_colours_all(),
        cpq_door_codes=admin_data.list_cpq_door_codes(),
        erp_status=admin_data.erp_sync_status(),
        erp_schedule=scheduled_sync.get_schedule(),
        orders_schedule=scheduled_sync.get_orders_schedule(),
        scrap_schedule=scheduled_sync.get_scrap_schedule(),
        users=db.list_users(),
        test_data_enabled=test_data.is_enabled(),
        test_so_number=test_data.SO_NUMBER,
        test_job_number=test_data.JOB_NUMBER,
        test_colour_name=test_data.COLOUR_NAME,
        audit_log=audit.list_recent(),
        app_version=version.get_version(),
    )


@bp.route("/api/admin/door-codes/unmapped")
@role_required("admin")
def api_unmapped_door_codes():
    """DISTINCT over all of coitem_all with no index on this column -- ~17s
    against the real ERP (confirmed 2026-10-20). Deliberately NOT loaded with
    the rest of admin_page(): it was blocking every single Admin page visit
    for that long before this was split out into its own on-demand call,
    triggered by a button rather than automatically."""
    try:
        return jsonify({"ok": True, "codes": erp_lookup.list_unmapped_cpq_codes()})
    except erp.ErpNotConfigured as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400
    except Exception as exc:
        logger.exception("Couldn't list unmapped CPQ door codes")
        return jsonify({"ok": False, "error": str(exc)}), 502


# ── SQL / ERP Connection ─────────────────────────────────────────────────

@bp.route("/api/admin/erp/test", methods=["POST"])
@role_required("admin")
def api_erp_test():
    ok, message = erp.test_connection()
    return jsonify({"ok": ok, "message": message})


@bp.route("/api/admin/erp/sync-items", methods=["POST"])
@role_required("admin")
def api_erp_sync_items():
    try:
        count = erp_sync.sync_items()
    except erp.ErpNotConfigured as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400
    except Exception as exc:
        logger.exception("Item sync failed")
        return jsonify({"ok": False, "error": str(exc)}), 502
    audit.log(_actor(), "erp.sync_items", detail={"count": count})
    return jsonify({"ok": True, "count": count})


@bp.route("/api/admin/erp/sync-colours", methods=["POST"])
@role_required("admin")
def api_erp_sync_colours():
    try:
        count = erp_sync.sync_colours()
    except erp.ErpNotConfigured as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400
    except Exception as exc:
        logger.exception("Colour sync failed")
        return jsonify({"ok": False, "error": str(exc)}), 502
    audit.log(_actor(), "erp.sync_colours", detail={"count": count})
    return jsonify({"ok": True, "count": count})


def _parse_schedule_payload(data: dict) -> tuple[str, str, int] | tuple[None, None, None]:
    """Shared validation for both schedule endpoints below. Returns
    (frequency, time_str, day_of_week) or (None, None, None) if invalid --
    caller turns that into a 400."""
    frequency = str(data.get("frequency", "")).strip()
    if frequency not in ("daily", "weekly", "monthly"):
        return None, None, None
    time_str = str(data.get("time", "")).strip()
    parts = time_str.split(":")
    if len(parts) != 2 or not all(p.isdigit() for p in parts):
        return None, None, None
    hh, mm = int(parts[0]), int(parts[1])
    if not (0 <= hh <= 23 and 0 <= mm <= 59):
        return None, None, None
    try:
        day_of_week = int(data.get("day_of_week", 0))
    except (TypeError, ValueError):
        return None, None, None
    if not (0 <= day_of_week <= 6):
        return None, None, None
    return frequency, f"{hh:02d}:{mm:02d}", day_of_week


@bp.route("/api/admin/erp/schedule", methods=["POST"])
@role_required("admin")
def api_set_erp_schedule():
    data = request.get_json(force=True, silent=True) or {}
    frequency, time_str, day_of_week = _parse_schedule_payload(data)
    if frequency is None:
        return jsonify({"ok": False, "error": "Invalid schedule"}), 400
    scheduled_sync.set_schedule(bool(data.get("enabled")), frequency, time_str, day_of_week)
    audit.log(_actor(), "erp.set_schedule", detail=data)
    return jsonify({"ok": True})


@bp.route("/api/admin/erp/sync-orders", methods=["POST"])
@role_required("admin")
def api_erp_sync_orders():
    """Manual "Sync Orders Now" -- for when someone needs a brand-new SO
    available immediately instead of waiting for the next scheduled run (see
    services/erp_lookup.py: the entry form only ever reads the local cache,
    never SyteLine live)."""
    try:
        result = erp_sync.sync_orders()
    except erp.ErpNotConfigured as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400
    except Exception as exc:
        logger.exception("Orders sync failed")
        return jsonify({"ok": False, "error": str(exc)}), 502
    audit.log(_actor(), "erp.sync_orders", detail=result)
    return jsonify({"ok": True, **result})


@bp.route("/api/admin/erp/orders-schedule", methods=["POST"])
@role_required("admin")
def api_set_orders_schedule():
    data = request.get_json(force=True, silent=True) or {}
    frequency, time_str, day_of_week = _parse_schedule_payload(data)
    if frequency is None:
        return jsonify({"ok": False, "error": "Invalid schedule"}), 400
    scheduled_sync.set_orders_schedule(bool(data.get("enabled")), frequency, time_str, day_of_week)
    audit.log(_actor(), "erp.set_orders_schedule", detail=data)
    return jsonify({"ok": True})


@bp.route("/api/admin/erp/sync-scrap", methods=["POST"])
@role_required("admin")
def api_erp_sync_scrap():
    """Manual "Sync Scrap Transactions Now" -- refreshes the "ERP actual"
    column on both Scrap write-off tabs (Turret and Rework log)."""
    try:
        count = erp_sync.sync_scrap_transactions()
    except erp.ErpNotConfigured as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400
    except Exception as exc:
        logger.exception("Scrap transactions sync failed")
        return jsonify({"ok": False, "error": str(exc)}), 502
    audit.log(_actor(), "erp.sync_scrap", detail={"count": count})
    return jsonify({"ok": True, "count": count})


@bp.route("/api/admin/erp/scrap-schedule", methods=["POST"])
@role_required("admin")
def api_set_scrap_schedule():
    data = request.get_json(force=True, silent=True) or {}
    frequency, time_str, day_of_week = _parse_schedule_payload(data)
    if frequency is None:
        return jsonify({"ok": False, "error": "Invalid schedule"}), 400
    scheduled_sync.set_scrap_schedule(bool(data.get("enabled")), frequency, time_str, day_of_week)
    audit.log(_actor(), "erp.set_scrap_schedule", detail=data)
    return jsonify({"ok": True})


@bp.route("/api/admin/test-data/toggle", methods=["POST"])
@role_required("admin")
def api_toggle_test_data():
    enabled = bool((request.get_json(force=True, silent=True) or {}).get("enabled"))
    if enabled:
        test_data.enable()
        audit.log(_actor(), "test_data.enable")
        return jsonify({"ok": True, "enabled": True})
    result = test_data.disable()
    audit.log(_actor(), "test_data.disable", detail=result)
    return jsonify({"ok": True, "enabled": False, **result})


# ── Reasons ────────────────────────────────────────────────────────────────

@bp.route("/api/admin/reasons", methods=["POST"])
@role_required("admin")
def api_create_reason():
    data = request.get_json(force=True, silent=True) or {}
    reason = str(data.get("reason", "")).strip()
    source = str(data.get("source", "")).strip()
    if not reason or not source:
        return jsonify({"ok": False, "error": "Reason and source are required"}), 400
    admin_data.create_reason(reason, data.get("code"), source, data.get("fault_category"))
    audit.log(_actor(), "reason.create", "reason", reason, data)
    return jsonify({"ok": True})


@bp.route("/api/admin/reasons/<path:reason>/active", methods=["POST"])
@role_required("admin")
def api_set_reason_active(reason: str):
    active = bool((request.get_json(force=True, silent=True) or {}).get("active", True))
    admin_data.set_reason_active(reason, active)
    audit.log(_actor(), "reason.set_active", "reason", reason, {"active": active})
    return jsonify({"ok": True})


@bp.route("/api/admin/reasons/<int:reason_id>", methods=["POST"])
@role_required("admin")
def api_update_reason(reason_id: int):
    data = request.get_json(force=True, silent=True) or {}
    reason = str(data.get("reason", "")).strip()
    source = str(data.get("source", "")).strip()
    if not reason or not source:
        return jsonify({"ok": False, "error": "Reason and source are required"}), 400
    try:
        updated = admin_data.save_reason(reason_id, reason, data.get("code"), source, data.get("fault_category"))
    except ValueError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 404
    except Exception as exc:
        logger.exception("Reason update failed for id %s", reason_id)
        return jsonify({"ok": False, "error": str(exc)}), 400
    audit.log(_actor(), "reason.save", "reason", reason_id, data)
    return jsonify({"ok": True, "updated_historical_rows": updated})


# ── Work centres ─────────────────────────────────────────────────────────

@bp.route("/api/admin/<any(work_centres):table>", methods=["POST"])
@role_required("admin")
def api_create_named(table: str):
    data = request.get_json(force=True, silent=True) or {}
    name = str(data.get("name", "")).strip()
    if not name:
        return jsonify({"ok": False, "error": "Name is required"}), 400
    raw_order = str(data.get("sort_order", "")).strip()
    try:
        sort_order = int(raw_order) if raw_order else None
    except ValueError:
        return jsonify({"ok": False, "error": "Sort order must be a whole number"}), 400
    admin_data.create_named(table, name, sort_order)
    audit.log(_actor(), f"{table}.create", table, name)
    return jsonify({"ok": True})


@bp.route("/api/admin/<any(work_centres):table>/<path:name>/active", methods=["POST"])
@role_required("admin")
def api_set_named_active(table: str, name: str):
    active = bool((request.get_json(force=True, silent=True) or {}).get("active", True))
    admin_data.set_named_active(table, name, active)
    audit.log(_actor(), f"{table}.set_active", table, name, {"active": active})
    return jsonify({"ok": True})


@bp.route("/api/admin/<any(work_centres):table>/<path:name>/save", methods=["POST"])
@role_required("admin")
def api_save_named(table: str, name: str):
    data = request.get_json(force=True, silent=True) or {}
    new_name = str(data.get("name", "")).strip()
    if not new_name:
        return jsonify({"ok": False, "error": "Name is required"}), 400
    try:
        sort_order = int(data.get("sort_order"))
    except (TypeError, ValueError):
        return jsonify({"ok": False, "error": "Sort order must be a whole number"}), 400
    try:
        updated = admin_data.save_named(table, name, new_name, sort_order)
    except Exception as exc:
        logger.exception("Save failed for %s %r -> %r", table, name, new_name)
        return jsonify({"ok": False, "error": str(exc)}), 400
    audit.log(_actor(), f"{table}.save", table, name, {"name": new_name, "sort_order": sort_order})
    return jsonify({"ok": True, "updated_historical_rows": updated})


# ── Colours (ERP-owned; local toggle only) ──────────────────────────────────

@bp.route("/api/admin/colours/<path:name>/active", methods=["POST"])
@role_required("admin")
def api_set_colour_active(name: str):
    active = bool((request.get_json(force=True, silent=True) or {}).get("active", True))
    admin_data.set_colour_active(name, active)
    audit.log(_actor(), "colour.set_active", "colour", name, {"active": active})
    return jsonify({"ok": True})


# ── Items & rates ────────────────────────────────────────────────────────

@bp.route("/api/admin/items/search")
@role_required("admin")
def api_search_items():
    return jsonify(admin_data.search_items_all(request.args.get("q", "")))


@bp.route("/api/admin/items/<path:part_number>/rule", methods=["POST"])
@role_required("admin")
def api_set_item_rule(part_number: str):
    try:
        rule = float((request.get_json(force=True, silent=True) or {}).get("rule"))
    except (TypeError, ValueError):
        return jsonify({"ok": False, "error": "Rule must be a number"}), 400
    admin_data.set_item_rule(part_number, rule)
    audit.log(_actor(), "item.set_rule", "item", part_number, {"rule": rule})
    return jsonify({"ok": True})


# ── CPQ door codes (SO-lookup autofill mapping) ─────────────────────────────

@bp.route("/api/admin/door-codes", methods=["POST"])
@role_required("admin")
def api_save_cpq_door_code():
    data = request.get_json(force=True, silent=True) or {}
    old_code = str(data.get("old_code") or "").strip() or None
    new_code = str(data.get("cpq_code", "")).strip()
    family_name = str(data.get("family_name", "")).strip()
    description = str(data.get("description", "")).strip()
    if not new_code or not family_name:
        return jsonify({"ok": False, "error": "Code and family name are required"}), 400
    pieces = {}
    for key in ("stile_pieces", "rail_pieces"):
        raw = str(data.get(key) if data.get(key) is not None else "").strip()
        try:
            pieces[key] = int(raw) if raw else None
        except ValueError:
            return jsonify({"ok": False, "error": "Pieces must be a whole number"}), 400
        if pieces[key] is not None and pieces[key] < 0:
            return jsonify({"ok": False, "error": "Pieces can't be negative"}), 400
    admin_data.save_cpq_door_code(old_code, new_code, family_name, description, pieces["stile_pieces"], pieces["rail_pieces"])
    audit.log(_actor(), "door_code.save", "door_code", new_code, {"old_code": old_code, "family_name": family_name, "description": description, **pieces})
    return jsonify({"ok": True})


@bp.route("/api/admin/door-codes/<path:cpq_code>/active", methods=["POST"])
@role_required("admin")
def api_set_cpq_door_code_active(cpq_code: str):
    active = bool((request.get_json(force=True, silent=True) or {}).get("active", True))
    admin_data.set_cpq_door_code_active(cpq_code, active)
    audit.log(_actor(), "door_code.set_active", "door_code", cpq_code, {"active": active})
    return jsonify({"ok": True})


