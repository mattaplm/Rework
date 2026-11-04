from concurrent.futures import ThreadPoolExecutor
from datetime import date
from decimal import Decimal
import sqlite3

import openpyxl
import pytest

import db
from services import admin_data, audit, erp_reconciliation, erp_sync, reference_data
from services import reporting, rework, rework_import, scheduled_sync, turret
from backup_sqlite import backup_database


@pytest.fixture
def sqlite_store(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_BACKEND", "sqlite")
    monkeypatch.setenv("SQLITE_PATH", str(tmp_path / "rework.sqlite3"))
    monkeypatch.setenv("ADMIN_DEFAULT_PASSWORD", "6543")
    monkeypatch.setenv("SQL_SERVER", "")
    monkeypatch.setenv("SQL_DATABASE", "")
    db.init_db()
    admin_data.create_reason("DAMAGE", "DMG", "Factory", None)
    admin_data.create_named("work_centres", "Assembly")
    with db.get_conn() as conn, conn.cursor() as cur:
        cur.execute("INSERT INTO items (part_number, description, std_cost, rule) VALUES (%s, %s, %s, %s)",
                    ("PART", "Door part", Decimal("12.50"), 2))
        cur.execute("INSERT INTO items (part_number, description, std_cost, plan_code) VALUES (%s, %s, %s, %s)",
                    ("SHEET", "Sheet stock", 10, "SHT"))
    return tmp_path


def payload(day=None):
    return dict(rework_date=str(day or date.today()), type="Replace Part", so_number="SO123",
                product_code="PART", quantity=3, reason="DAMAGE", colour="Black",
                door_type="Axis", work_centre="Assembly")


def test_restart_transactions_foreign_keys_and_parallel_writes(sqlite_store):
    user_id = db.create_user("viewer", None, "viewer", False)
    db.init_db()
    assert db.get_user(user_id)["password_hash"] is None
    with pytest.raises(RuntimeError):
        with db.get_conn() as conn, conn.cursor() as cur:
            cur.execute("INSERT INTO settings VALUES (%s, %s)", ("rolled_back", "value"))
            raise RuntimeError("abort")
    with db.get_conn() as conn, conn.cursor() as cur:
        cur.execute("SELECT value FROM settings WHERE key = %s", ("rolled_back",))
        assert cur.fetchone() is None
    with pytest.raises(sqlite3.IntegrityError):
        db.create_session("invalid", 9999, "nobody", "viewer", "", "")
    with ThreadPoolExecutor(max_workers=4) as workers:
        ids = list(workers.map(lambda i: db.create_user(f"user{i}", None, "viewer", False), range(12)))
    assert len(set(ids)) == 12
    db.create_session("valid", user_id, "viewer", "viewer", "", "")
    assert any(s["sid"] == "valid" for s in db.list_active_sessions())
    db.delete_user(user_id)
    assert db.get_session("valid") is None


def test_entries_reporting_search_and_iso_writeoffs(sqlite_store):
    event = rework.create_event(payload(date(2025, 12, 31)), 1)
    assert event["material_cost"] == 75
    assert isinstance(event["rework_date"], date)
    with db.get_conn() as conn, conn.cursor() as cur:
        cur.execute("UPDATE rework_events SET entered_date = %s WHERE id = %s", (date(2025, 12, 31), event["id"]))
    assert len(rework.list_events(filters={"year": "2025", "month": "12", "so_number": "so123"})) == 1
    assert reference_data.search_items("door")[0]["part_number"] == "PART"
    assert reporting.summary(None)["total_cost"] == 75
    assert reporting.summary(1)["total_entries"] == 0
    assert reporting.weekly_trend(None)[0]["week_start"] == "2025-12-29"
    assert reporting.top_reasons(days=None)[0]["reason"] == "DAMAGE"
    assert reporting.by_colour(days=None)[0]["colour"] == "Black"
    assert reporting.by_door_type(days=None)[0]["door_type"] == "Axis"
    summary = rework.scrap_writeoff_summary(2, 2026)[0]
    assert summary["total_qty"] == 6
    assert summary["write_off_date"] == date(2026, 1, 5)
    assert summary["from_week"] == 1
    assert rework.list_available_writeoff_weeks() == [{"write_off_year": 2026, "write_off_week": 2}]
    assert rework.list_available_years() == [2025]
    audit.log("admin", "test", "rework", event["id"], {"ok": True})
    assert audit.list_recent()[0]["detail"] == {"ok": True}


def _turret_job(**extra):
    return {**dict(sales_number="SO1", door_type="Axis", colour="Black", sheet_a="SHEET", qty_a=1), **extra}


def _rework(sheet="SHEET", qty=2, rework_id=None, rework_type="Replacement Parts"):
    return {"id": rework_id, "rework_type": rework_type, "reason": "DAMAGE",
            "materials": [{"sheet": sheet, "qty": qty}]}


def test_turret_edit_and_writeoff_week_arrays(sqlite_store, monkeypatch):
    monkeypatch.setattr(turret, "_today", lambda: date(2025, 12, 31))
    event_id = turret.create_event(_turret_job(event_date="2020-01-01"), 1)
    event = turret.get_event(event_id)
    assert event["event_date"] == date(2025, 12, 31)  # stamped server-side, client value ignored
    assert event["reworks"] == []

    turret.update_event(event_id, _turret_job(reworks=[_rework()]))
    first = turret.get_event(event_id)["reworks"][0]
    assert first["scrap_date_a"] == date(2025, 12, 31)
    monkeypatch.setattr(turret, "_today", lambda: date(2026, 1, 9))
    turret.update_event(event_id, _turret_job(reworks=[_rework(rework_id=first["id"])]))
    again = turret.get_event(event_id)
    assert again["reworks"][0]["id"] == first["id"]
    assert again["reworks"][0]["scrap_date_a"] == date(2025, 12, 31)  # not re-stamped
    assert again["event_date"] == date(2025, 12, 31)  # entry date never moves

    rows = turret.scrap_summary_by_week(2, 2026)
    assert rows[0]["from_weeks"] == [1]
    assert rows[0]["total_qty"] == 2
    assert turret.list_available_scrap_weeks() == [{"write_off_year": 2026, "write_off_week": 2}]
    assert len(turret.list_events(filters={"year": "2025", "month": "12"})) == 1


def test_turret_multiple_reworks_options_and_usage(sqlite_store, monkeypatch):
    monkeypatch.setattr(turret, "_today", lambda: date(2026, 11, 4))  # a Wednesday
    assert turret.list_options("turret_open_options") == ["LH IN", "RH IN", "LH OUT", "RH OUT"]
    admin_data.create_named("turret_variations", "More sheets used")
    event_id = turret.create_event(_turret_job(
        sales_number="S000123", open_status="LH IN", variation="More sheets used",
        reworks=[_rework(qty=2), _rework(qty=3, rework_type="Rework Entire Door"), {"reason": "", "materials": []}],
    ), 1)
    event = turret.get_event(event_id)
    assert event["open_status"] == "LH IN" and event["variation"] == "More sheets used"
    assert [r["scrap_qty_a"] for r in event["reworks"]] == [2, 3]  # blank rework dropped
    assert float(event["scrap_cost"]) == 50.0  # (2 + 3) x $10
    listed = turret.list_events(filters={"sales_number": "s000123"})
    assert len(listed) == 1 and float(listed[0]["rework_qty"]) == 5
    assert turret.list_events(filters={"sales_number": "nope"}) == []

    # Removing a rework deletes it; the job total follows.
    keep = event["reworks"][1]
    turret.update_event(event_id, _turret_job(sales_number="S000123", variation="More sheets used",
                                              reworks=[_rework(qty=3, rework_id=keep["id"])]))
    event = turret.get_event(event_id)
    assert [r["id"] for r in event["reworks"]] == [keep["id"]] and float(event["scrap_cost"]) == 30.0

    with pytest.raises(turret.ValidationError):
        turret.update_event(event_id, _turret_job(reworks=[_rework(rework_type="Bogus")]))

    # Renaming a variation cascades into turret_events.
    assert admin_data.save_named("turret_variations", "More sheets used", "EX(+) More sheets", 1) == 1
    assert turret.get_event(event_id)["variation"] == "EX(+) More sheets"

    usage = turret.daily_usage(date(2026, 11, 4), date(2026, 11, 4))
    assert usage == [{"item": "SHEET", "description": "Sheet stock", "used": 1.0, "scrapped": 3.0, "jobs": 1, "total": 4.0}]
    assert turret.daily_usage(date(2026, 11, 5), date(2026, 11, 30)) == []

    today = date(2026, 11, 4)
    assert turret.usage_period("today", today=today)[1:] == (today, today)
    assert turret.usage_period("this_week", today=today)[1:] == (date(2026, 11, 2), date(2026, 11, 8))
    assert turret.usage_period("last_week", today=today)[1:] == (date(2026, 10, 26), date(2026, 11, 1))
    assert turret.usage_period("last_month", today=today)[1:] == (date(2026, 10, 1), date(2026, 10, 31))
    assert turret.usage_period("this_month", today=date(2026, 12, 15))[1:] == (date(2026, 12, 1), date(2026, 12, 31))
    assert turret.usage_period("custom", "2026-11-10", "2026-11-01", today=today)[1:] == (date(2026, 11, 1), date(2026, 11, 10))
    assert turret.usage_period("junk", today=today)[0] == "today"


def test_turret_historical_scrap_moves_into_reworks_keeping_dates(sqlite_store):
    with db.get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            "INSERT INTO turret_events (event_date, sales_number, door_type, colour, sheet_a, "
            "scrap_sheet_a, scrap_qty_a, scrap_date_a, source_row_hash) "
            "VALUES (%s, 'SO9', 'Axis', 'Black', 'SHEET', 'SHEET', 4, %s, 'hash') RETURNING id",
            (date(2025, 3, 3), date(2025, 3, 4)),
        )
        event_id = cur.fetchone()["id"]
    legacy = turret.get_event(event_id)["reworks"]
    assert len(legacy) == 1 and legacy[0]["id"] == "legacy"
    turret.update_event(event_id, _turret_job(sales_number="SO9", reworks=[
        _rework(qty=4, rework_id="legacy"), _rework(qty=1)]))
    event = turret.get_event(event_id)
    assert event["scrap_qty_a"] is None  # moved off the parent row
    assert [r["scrap_date_a"] for r in event["reworks"]][0] == date(2025, 3, 4)
    assert sum(r["total_qty"] for r in turret.scrap_summary_by_week()) == 5  # not double-counted


def test_erp_upserts_cleanup_and_schedule_timestamps(sqlite_store, monkeypatch):
    item = dict(part_number="PART", description="ERP part", product_code="P", product_group="DOORS",
                std_cost=Decimal("15.75"), length_std=0, plan_code=None)
    monkeypatch.setattr(erp_sync.erp, "fetch_all", lambda *args: [item])
    assert erp_sync.sync_items() == 1
    assert reference_data.get_item("PART")["rule"] == 2
    assert scheduled_sync._oldest_last_synced().tzinfo is not None
    assert admin_data.erp_sync_status()["items_synced"] == 1
    monkeypatch.setattr(erp_sync.erp, "fetch_all", lambda *args: [])
    erp_sync.sync_items()
    assert reference_data.get_item("PART") is None
    assert reference_data.get_item("SHEET") is not None  # local entries survive
    colour = dict(ColourDescription="Black", Colour="BK", RGB="000000")
    monkeypatch.setattr(erp_sync.erp, "fetch_all", lambda *args: [colour])
    erp_sync.sync_colours()
    monkeypatch.setattr(erp_sync.erp, "fetch_all", lambda *args: [])
    erp_sync.sync_colours()
    assert admin_data.list_colours_all()[0]["active"] == 0
    txn = dict(txn_date=date(2026, 1, 5), item="SHEET", description="Sheet", qty=-2,
               scrap_cost=-20, scrap_labour_cost=0, product_group="D", product_code="P", type="I", user_code="U")
    monkeypatch.setattr(erp_sync.erp, "fetch_all", lambda *args: [txn])
    erp_sync.sync_scrap_transactions()
    erp_sync.sync_scrap_transactions()
    assert len(erp_reconciliation.erp_actuals_by_item_week()) == 1
    scheduled_sync.set_schedule(False, "weekly", "02:00", 0)
    assert scheduled_sync.get_schedule()["enabled"] is False


def test_excel_import_deduplicates(sqlite_store):
    path = sqlite_store / "sample.xlsx"
    book = openpyxl.Workbook()
    sheet = book.active
    sheet.title = "REWORK"
    sheet.append(["header"] * 21)
    row = [None] * 21
    values = dict(entered_date=date.today(), rework_date=date.today(), type="Replace Part",
                  so_number="IMPORT", product_code="PART", quantity=1, reason="DAMAGE", colour="Black",
                  door_type="Axis", work_centre="Assembly", material_cost=12.5, qty_to_remove=1)
    for name, value in values.items():
        row[rework_import.COL[name]] = value
    sheet.append(row)
    book.save(path)
    book.close()
    assert rework_import.import_workbook(str(path)).inserted == 1
    result = rework_import.import_workbook(str(path))
    assert result.inserted == 0 and result.skipped_duplicate == 1


def test_http_login_pin_change_and_all_pages(sqlite_store, monkeypatch):
    monkeypatch.setattr(scheduled_sync, "start_background_thread", lambda: None)
    from app import create_app
    app = create_app()
    app.config["TESTING"] = True
    client = app.test_client()
    assert client.post("/login", data={"username": "admin", "password": "wrong"}).status_code == 401
    response = client.post("/login", data={"username": "admin", "password": "6543"})
    assert response.location.endswith("/change-password")
    assert client.post("/change-password", data={"new_password": "5678", "confirm": "5678"}).status_code == 302
    for path in ("/dashboard", "/rework", "/rework/new", "/turret", "/turret?sales_number=S00", "/turret/new",
                 "/turret/usage", "/turret/usage?period=last_week", "/turret/usage?period=custom&start=2026-01-01&end=bad",
                 "/admin", "/import"):
        assert client.get(path).status_code == 200, path
    assert client.post("/api/rework-events", json=payload()).status_code == 400  # Person is required
    posted = client.post("/api/rework-events", json={**payload(), "person": "gary"})
    assert posted.status_code == 200
    assert posted.get_json()["event"]["entered_by_name"] == "Gary"  # matched/created case-insensitively
    assert client.get("/rework").status_code == 200
    turret_job = {"sales_number": "SO1", "door_type": "Axis", "colour": "Black", "sheet_a": "SHEET", "qty_a": 1,
                  "open_status": "RH IN", "reworks": [{"rework_type": "Replacement Parts", "reason": "DAMAGE",
                                                       "materials": [{"sheet": "SHEET", "qty": 1}]}]}
    created = client.post("/api/turret-events", json=turret_job)
    assert created.status_code == 200
    turret_id = created.get_json()["id"]
    assert client.get(f"/turret/{turret_id}/edit").status_code == 200
    assert client.post(f"/api/turret-events/{turret_id}", json=turret_job).status_code == 200
    assert client.post("/api/admin/turret_variations", json={"name": "Sheet swapped"}).status_code == 200
    assert client.post("/logout").status_code == 302
    assert client.get("/api/users").status_code == 401


def test_online_backup_restores_entries_and_survives_restart(sqlite_store, monkeypatch):
    original = rework.create_event(payload(), 1)
    backup = backup_database(sqlite_store / "rework.sqlite3", sqlite_store / "backups")
    rework.create_event(payload(), 1)
    assert len(rework.list_events()) == 2
    monkeypatch.setenv("SQLITE_PATH", str(backup))
    db.init_db()
    assert [row["id"] for row in rework.list_events()] == [original["id"]]
    assert reporting.summary(None)["total_cost"] == 75
