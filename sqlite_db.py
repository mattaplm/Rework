"""SQLite DB-API adapter for the application's parameterized SQL and dict rows.

SQL dialect differences belong in db.py's expression helpers, not a SQL-text
translator. This adapter only changes parameter markers and Python value types.
"""

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
import json
from pathlib import Path
import re
import sqlite3


_DATES = {"entered_date", "rework_date", "due_date", "event_date", "txn_date",
          "scrap_date_a", "scrap_date_b", "scrap_date_c", "write_off_date"}
_TIMES = {"created_at", "updated_at", "synced_at", "last_login_at",
          "last_seen_at", "at", "t", "last_synced", "applied_at"}
_BOOLEANS = {"active", "must_change_password", "includes_test_data"}


def _bind(value):
    if isinstance(value, datetime):
        return value.isoformat(sep=" ")
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, (list, tuple)):
        return json.dumps(value)
    return value


def _row(cursor, values):
    result = {}
    for column, value in zip(cursor.description, values):
        key = column[0]
        if value is not None:
            if key in _DATES:
                value = _parse_day(value)
            elif key in _TIMES:
                value = datetime.fromisoformat(value)
                if value.tzinfo is None:
                    value = value.replace(tzinfo=timezone.utc)
            elif key == "from_weeks":
                value = json.loads(value)
            elif key in _BOOLEANS:
                value = bool(value)
        result[key] = value
    return result


def _parse_day(value):
    """None for NULL or anything that isn't an ISO date (SQLite doesn't
    type-check columns the way Postgres DATE does), so one junk cell can't
    crash a whole query."""
    try:
        return date.fromisoformat(str(value)[:10])
    except (TypeError, ValueError):
        return None


def _date_part(part, value):
    day = _parse_day(value)
    if day is None:
        return None
    return {"year": day.year, "month": day.month,
            "week": day.isocalendar().week, "isoyear": day.isocalendar().year}[part.lower()]


def _week_start(value):
    day = _parse_day(value)
    if day is None:
        return None
    return (day - timedelta(days=day.weekday())).isoformat()


def _date_shift(value, days):
    day = _parse_day(value)
    if day is None:
        return None
    return (day + timedelta(days=days)).isoformat()


class _SortedArray:
    def __init__(self):
        self.values = set()

    def step(self, value):
        if value is not None:
            self.values.add(value)

    def finalize(self):
        return json.dumps(sorted(self.values))


class Cursor:
    def __init__(self, connection):
        self.connection = connection
        self.raw = connection.raw.cursor()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.raw.close()

    def execute(self, query, params=None):
        query = re.sub(r"%\((\w+)\)s", r":\1", query).replace("%s", "?")
        if params is None:
            params = ()
        elif isinstance(params, dict):
            params = {key: _bind(value) for key, value in params.items()}
        else:
            params = tuple(_bind(value) for value in params)
        # A top-level SAVEPOINT would commit on RELEASE. Keep workbook imports
        # inside the connection's outer transaction so failures can roll back.
        if query.lstrip().upper().startswith("SAVEPOINT") and not self.connection.raw.in_transaction:
            self.connection.raw.execute("BEGIN")
        self.raw.execute(query, params)
        return self

    def fetchone(self):
        return self.raw.fetchone()

    def fetchall(self):
        return self.raw.fetchall()

    @property
    def rowcount(self):
        return self.raw.rowcount


class Connection:
    def __init__(self, path):
        path = Path(path).expanduser().resolve()
        path.parent.mkdir(parents=True, exist_ok=True)
        self.raw = sqlite3.connect(path, timeout=30)
        self.raw.row_factory = _row
        self.raw.execute("PRAGMA foreign_keys=ON")
        self.raw.execute("PRAGMA busy_timeout=30000")
        self.raw.create_function("now", 0, lambda: datetime.now(timezone.utc).isoformat(sep=" "))
        self.raw.create_function("date_part", 2, _date_part, deterministic=True)
        self.raw.create_function("week_start", 1, _week_start, deterministic=True)
        self.raw.create_function("date_shift", 2, _date_shift, deterministic=True)
        self.raw.create_aggregate("sorted_array", 1, _SortedArray)

    def cursor(self):
        return Cursor(self)

    def commit(self):
        self.raw.commit()

    def rollback(self):
        self.raw.rollback()

    def close(self):
        self.raw.close()
