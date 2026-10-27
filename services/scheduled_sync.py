"""Background scheduled ERP sync -- runs services.erp_sync.sync_items/
sync_colours/sync_orders at a fixed clock time, independent of Admin -> SQL
Connection's manual Sync buttons (which still work exactly as before).
Settings-backed (enabled flag + frequency + time-of-day + day-of-week for
weekly), using the same `settings` key/value table as everything else in
this app that needs one persistent value -- no new table for a handful of
scalars.

A schedule is "due" when now has passed the most recent scheduled clock time
(today's HH:MM for daily, this week's weekday+HH:MM for weekly) and the last
sync happened before that time -- not a rolling "N hours since last sync"
interval. That means "daily at 02:00" always means 2am, not "some time in a
~24h window that drifts with whenever the background thread last woke up" --
the distinction the admin UI is actually asking for when it lets someone
pick a time. Monthly stays a simple ~30-day rolling check (no admin-facing
day-of-month picker yet -- not asked for).

"Last synced" isn't tracked separately here -- `items`/`colours.synced_at`
(already written by every sync, manual or scheduled) is the source of truth
for the items/colours schedule, read via the OLDER of the two tables' most
recent sync so neither one can silently drift past due while the other looks
current. `synced_orders.synced_at` is the source of truth for the orders
schedule.

Orders get their own, separate schedule (`get_orders_schedule`/
`set_orders_schedule`/`run_orders_sync_if_due`) rather than sharing the
items/colours one: the entry form's SO lookup depends on it directly (see
services/erp_lookup.py), so it defaults to daily and *enabled*, unlike
items/colours which default to weekly.

Scrap transactions (`get_scrap_schedule`/`set_scrap_schedule`/
`run_scrap_sync_if_due`) get a third schedule, defaulting to weekly on
Monday -- matches the department's own "scrap every Monday for last week"
write-off cadence, so a Monday-morning sync naturally picks up whatever
landed in SyteLine from the week just finished. All three schedules are
checked from the same background thread.
"""

from __future__ import annotations

import logging
import threading
import time
from datetime import datetime, timedelta, timezone

import db
from services import erp_sync

logger = logging.getLogger(__name__)

_CHECK_INTERVAL_SECONDS = 30 * 60  # how often the background thread checks whether a sync is due

# day_of_week: 0 = Monday ... 6 = Sunday (Python's datetime.weekday() convention)
_DEFAULTS = {"frequency": "weekly", "time": "02:00", "day_of_week": 0}
_ORDERS_DEFAULTS = {"frequency": "daily", "time": "02:00", "day_of_week": 0}
_SCRAP_DEFAULTS = {"frequency": "weekly", "time": "06:00", "day_of_week": 0}


def _get_schedule(prefix: str, defaults: dict) -> dict:
    keys = [f"{prefix}_enabled", f"{prefix}_frequency", f"{prefix}_time", f"{prefix}_day"]
    with db.get_conn() as conn, conn.cursor() as cur:
        cur.execute("SELECT key, value FROM settings WHERE key = ANY(%s)", (keys,))
        rows = {r["key"]: r["value"] for r in cur.fetchall()}
    return {
        "enabled": rows.get(f"{prefix}_enabled", "true") == "true",
        "frequency": rows.get(f"{prefix}_frequency") or defaults["frequency"],
        "time": rows.get(f"{prefix}_time") or defaults["time"],
        "day_of_week": int(rows.get(f"{prefix}_day", defaults["day_of_week"])),
    }


def _set_schedule(prefix: str, enabled: bool, frequency: str, time_str: str, day_of_week: int) -> None:
    with db.get_conn() as conn, conn.cursor() as cur:
        for key, value in (
            (f"{prefix}_enabled", "true" if enabled else "false"),
            (f"{prefix}_frequency", frequency),
            (f"{prefix}_time", time_str),
            (f"{prefix}_day", str(day_of_week)),
        ):
            cur.execute(
                "INSERT INTO settings (key, value) VALUES (%s, %s) "
                "ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value",
                (key, value),
            )


def _most_recent_due(now: datetime, frequency: str, time_str: str, day_of_week: int) -> datetime:
    """The latest scheduled clock-time at or before `now` (both tz-aware, same tz)."""
    hh, mm = (int(p) for p in time_str.split(":"))
    candidate = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
    if frequency == "weekly":
        candidate -= timedelta(days=(candidate.weekday() - day_of_week) % 7)
    if candidate > now:
        candidate -= timedelta(days=7 if frequency == "weekly" else 1)
    return candidate


def _is_due(schedule: dict, last_synced: datetime | None) -> bool:
    if not schedule["enabled"]:
        return False
    if schedule["frequency"] == "monthly":
        if last_synced is None:
            return True
        age_days = (datetime.now(timezone.utc) - last_synced.astimezone(timezone.utc)).total_seconds() / 86400
        return age_days >= 30
    if last_synced is None:
        return True
    now = datetime.now().astimezone()
    due_at = _most_recent_due(now, schedule["frequency"], schedule["time"], schedule["day_of_week"])
    return last_synced.astimezone() < due_at


def get_schedule() -> dict:
    return _get_schedule("erp_sync", _DEFAULTS)


def set_schedule(enabled: bool, frequency: str, time_str: str, day_of_week: int) -> None:
    _set_schedule("erp_sync", enabled, frequency, time_str, day_of_week)


def _oldest_last_synced() -> datetime | None:
    with db.get_conn() as conn, conn.cursor() as cur:
        cur.execute("SELECT MAX(synced_at) AS t FROM items WHERE synced_at IS NOT NULL")
        items_t = cur.fetchone()["t"]
        cur.execute("SELECT MAX(synced_at) AS t FROM colours WHERE synced_at IS NOT NULL")
        colours_t = cur.fetchone()["t"]
    times = [t for t in (items_t, colours_t) if t]
    return min(times) if times else None


def run_if_due() -> bool:
    """Runs the sync if enabled and the scheduled clock-time has passed since
    the last sync. Returns whether it ran -- mainly so tests/manual calls can
    tell without parsing logs."""
    if not _is_due(get_schedule(), _oldest_last_synced()):
        return False
    try:
        items_count = erp_sync.sync_items()
        colours_count = erp_sync.sync_colours()
        logger.info("Scheduled ERP sync ran: %s items, %s colours", items_count, colours_count)
    except Exception:
        logger.exception("Scheduled ERP sync failed")
    return True


def get_orders_schedule() -> dict:
    return _get_schedule("orders_sync", _ORDERS_DEFAULTS)


def set_orders_schedule(enabled: bool, frequency: str, time_str: str, day_of_week: int) -> None:
    _set_schedule("orders_sync", enabled, frequency, time_str, day_of_week)


def _orders_last_synced() -> datetime | None:
    with db.get_conn() as conn, conn.cursor() as cur:
        cur.execute("SELECT MAX(synced_at) AS t FROM synced_orders")
        return cur.fetchone()["t"]


def run_orders_sync_if_due() -> bool:
    if not _is_due(get_orders_schedule(), _orders_last_synced()):
        return False
    try:
        result = erp_sync.sync_orders()
        logger.info("Scheduled ERP orders sync ran: %s", result)
    except Exception:
        logger.exception("Scheduled ERP orders sync failed")
    return True


def get_scrap_schedule() -> dict:
    return _get_schedule("scrap_sync", _SCRAP_DEFAULTS)


def set_scrap_schedule(enabled: bool, frequency: str, time_str: str, day_of_week: int) -> None:
    _set_schedule("scrap_sync", enabled, frequency, time_str, day_of_week)


def _scrap_last_synced() -> datetime | None:
    with db.get_conn() as conn, conn.cursor() as cur:
        cur.execute("SELECT MAX(synced_at) AS t FROM erp_scrap_transactions")
        return cur.fetchone()["t"]


def run_scrap_sync_if_due() -> bool:
    if not _is_due(get_scrap_schedule(), _scrap_last_synced()):
        return False
    try:
        count = erp_sync.sync_scrap_transactions()
        logger.info("Scheduled ERP scrap-transactions sync ran: %s rows", count)
    except Exception:
        logger.exception("Scheduled ERP scrap-transactions sync failed")
    return True


def start_background_thread() -> None:
    """Started once from app.py, same pattern as Scheduler's own scheduled-
    tasks thread. A no-op loop (cheap: a couple of queries every 30 minutes)
    when all schedules are disabled or SQL_SERVER isn't configured --
    run_if_due/run_orders_sync_if_due/run_scrap_sync_if_due/erp_sync already
    handle all of that gracefully. Checking every 30 minutes (not every
    minute) means a scheduled time can run up to ~30 minutes late -- fine
    for a daily/weekly reference-data sync, not worth a tighter loop."""

    def loop():
        while True:
            try:
                run_if_due()
            except Exception:
                logger.exception("Scheduled ERP sync check failed")
            try:
                run_orders_sync_if_due()
            except Exception:
                logger.exception("Scheduled ERP orders sync check failed")
            try:
                run_scrap_sync_if_due()
            except Exception:
                logger.exception("Scheduled ERP scrap-transactions sync check failed")
            time.sleep(_CHECK_INTERVAL_SECONDS)

    threading.Thread(target=loop, daemon=True, name="erp-sync-scheduler").start()
