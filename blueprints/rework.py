from __future__ import annotations

import logging

from flask import Blueprint, jsonify, render_template, request

from services import audit, erp_lookup, reference_data, test_data
from services import rework as rework_service
from services.auth import current_user, role_required

logger = logging.getLogger(__name__)
bp = Blueprint("rework", __name__)


@bp.route("/rework")
def list_page():
    filters = {
        "year": request.args.get("year") or None,
        "month": request.args.get("month") or None,
        "door_type": request.args.get("door_type") or None,
        "reason": request.args.get("reason") or None,
        "work_centre": request.args.get("work_centre") or None,
        "so_number": request.args.get("so_number") or None,
    }
    events = rework_service.list_events(limit=200, filters=filters)

    # The fake test SO (Admin -> SQL Connection -> Test data) is only ever
    # meant to be visible to admins testing the entry forms -- a real
    # operator/viewer doing real work shouldn't see test rows mixed into
    # their log (confirmed 2026-10-22: a real operator ran into this).
    # Admin's own view is unfiltered, since that's exactly who needs to see
    # it to use/verify the feature.
    user = current_user()
    if not user or user["role"] != "admin":
        events = [e for e in events if not (e.get("so_number") and e["so_number"].lower() == test_data.SO_NUMBER.lower())]

    available_weeks = rework_service.list_available_writeoff_weeks()
    write_off_week = request.args.get("write_off_week") or None
    write_off_year = request.args.get("write_off_year") or None
    # Only default on a genuinely fresh page load (neither param present at
    # all) -- an explicit "All weeks" choice submits both params empty,
    # which must stay "no filter", not silently bounce back to this default.
    if "write_off_week" not in request.args and "write_off_year" not in request.args and available_weeks:
        # An unfiltered view across years of history is thousands of rows,
        # not useful as a landing view (unlike Turret's write-off tab, which
        # only has a few months of data so "all weeks" is still browsable).
        write_off_year = str(available_weeks[0]["write_off_year"])
        write_off_week = str(available_weeks[0]["write_off_week"])
    writeoff_rows = rework_service.scrap_writeoff_summary(
        int(write_off_week) if write_off_week else None,
        int(write_off_year) if write_off_year else None,
    )
    if not user or user["role"] != "admin":
        writeoff_rows = [r for r in writeoff_rows if not r.get("includes_test_data")]

    return render_template(
        "rework_list.html",
        active="log",
        events=events,
        filters=filters,
        years=rework_service.list_available_years(),
        door_types=reference_data.list_door_types(),
        reasons=[r["reason"] for r in reference_data.list_reasons()],
        work_centres=reference_data.list_work_centres(),
        writeoff_rows=writeoff_rows,
        write_off_week=write_off_week,
        write_off_year=write_off_year,
        available_weeks=available_weeks,
        test_so_number=test_data.SO_NUMBER,
    )


@bp.route("/rework/new")
@role_required("operator")
def new_page():
    return render_template(
        "rework_new.html",
        active="new_entry",
        types=["Rework / Recoat", "Replace Part", "Scrap Entire Door"],
        reasons=reference_data.list_reasons(),
        door_types=reference_data.list_door_types(),
        work_centres=reference_data.list_work_centres(),
        colours=reference_data.list_colours(),
        test_so_number=test_data.SO_NUMBER,
    )


@bp.route("/api/rework-events", methods=["POST"])
@role_required("operator")
def api_create():
    payload = request.get_json(force=True, silent=True) or {}
    user = current_user()
    try:
        event = rework_service.create_event(payload, user_id=user["id"] if user else None)
    except rework_service.ValidationError as exc:
        return jsonify({"ok": False, "errors": exc.errors}), 400
    audit.log(
        user["username"] if user else "unknown", "rework_event.create", "rework_event", event["id"],
        {"type": event["type"], "so_number": event["so_number"], "product_code": event["product_code"], "quantity": str(event["quantity"])},
    )
    return jsonify({"ok": True, "event": event})


@bp.route("/api/items/search")
def api_item_search():
    query = request.args.get("q", "").strip()
    if len(query) < 2:
        return jsonify([])
    return jsonify(reference_data.search_items(query))


@bp.route("/api/items/<path:part_number>")
def api_item_lookup(part_number: str):
    item = reference_data.get_item(part_number)
    if not item:
        return jsonify(None), 404
    return jsonify(item)


@bp.route("/api/cost-preview", methods=["POST"])
def api_cost_preview():
    """Server-side authoritative cost calc for the live preview -- the form's
    JS calls this on every relevant change instead of re-implementing the
    costing rules in JavaScript, so there's exactly one place they live.

    `full_door_material_cost` here is client-supplied (from the earlier
    /api/orders/<so> lookup) and used for preview display ONLY -- this route
    never writes anything. The actual save (api_create -> create_event)
    ignores any client value for this and re-derives it itself live from the
    SO number, so a tampered preview can never change what gets stored."""
    from services.costing import compute_costs

    payload = request.get_json(force=True, silent=True) or {}
    item = reference_data.get_item(payload.get("product_code", ""))
    try:
        quantity = float(payload.get("quantity") or 0)
    except (TypeError, ValueError):
        quantity = 0
    full_door_cost = payload.get("full_door_material_cost")
    full_door_cost = float(full_door_cost) if full_door_cost is not None else None

    costs = compute_costs(payload.get("type", ""), quantity, item, full_door_cost)
    return jsonify({
        "matched": item is not None,
        "description": item["description"] if item else None,
        "qty_to_remove": costs.qty_to_remove,
        "material_cost": costs.material_cost,
        "total_cost": costs.total_cost,
    })


@bp.route("/api/orders/<path:so_number>")
def api_order_lookup(so_number: str):
    """Entry form's SO-number autofill (Job Number, Height, Width, Colour, a
    Door Type suggestion, this job's real material list, and the full door's
    material cost for Scrap Entire Door). Reads the local synced_orders cache
    (refreshed once a day), not SyteLine live -- see services/erp_lookup.py's
    docstring. A brand-new SO won't show up here until the next sync (or a
    manual "Sync Orders Now" from Admin)."""
    try:
        order = erp_lookup.lookup_order(so_number)
    except Exception as exc:
        logger.exception("Order lookup failed for %s", so_number)
        return jsonify({"ok": False, "error": str(exc)}), 502
    if not order:
        return jsonify({"ok": False, "error": "Sales order not found in the local cache. Try again after the next sync, or ask an admin to run one."}), 404
    return jsonify({"ok": True, "order": order})
