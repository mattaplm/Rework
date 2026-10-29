"""Read-only aggregate queries behind the Dashboard -- replaces the
spreadsheet's pivot sheets (weekly fault trend, cost pivot, top ten rework,
colour/door-type pivots).

`days=None` (and `weekly_trend`'s `weeks=None`) means "all time", no lower
bound on rework_date -- real history goes back to Jan 2023 (the original
`REWORK` sheet import), so a hard cap of 365 days left most of it
unreachable from the Dashboard (requested 2026-10-23: "show bigger time
range"). Every function takes the same `days` shape so blueprints/
dashboard.py can pass one parsed value through to all of them."""

from __future__ import annotations

from datetime import timedelta

import db


def summary(days: int | None = 90) -> dict:
    where = "WHERE rework_date >= %(since)s" if days is not None else ""
    with db.get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            f"""
            SELECT
                COUNT(*) AS total_entries,
                CAST((COALESCE(SUM(material_cost), 0) + COALESCE(SUM(labour_cost), 0)) AS DOUBLE PRECISION) AS total_cost,
                COUNT(*) FILTER (WHERE type = 'Rework / Recoat') AS rework_count,
                COUNT(*) FILTER (WHERE type = 'Replace Part') AS replace_count,
                COUNT(*) FILTER (WHERE type = 'Scrap Entire Door') AS scrap_count
            FROM rework_events
            {where}
            """,
            {"since": db.nz_now().date() - timedelta(days=days or 0)},
        )
        return cur.fetchone()


def weekly_trend(weeks: int | None = 12) -> list[dict]:
    where = "WHERE rework_date >= %(since)s" if weeks is not None else ""
    with db.get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            f"""
            SELECT {db.week_start('rework_date')} AS week_start,
                   COUNT(*) AS entries,
                   CAST((COALESCE(SUM(material_cost), 0) + COALESCE(SUM(labour_cost), 0)) AS DOUBLE PRECISION) AS total_cost
            FROM rework_events
            {where}
            GROUP BY 1 ORDER BY 1
            """,
            {"since": db.nz_now().date() - timedelta(weeks=weeks or 0)},
        )
        return cur.fetchall()


def top_reasons(limit: int = 8, days: int | None = 90) -> list[dict]:
    where = "WHERE rework_date >= %(since)s" if days is not None else ""
    with db.get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            f"""
            SELECT reason, COUNT(*) AS entries,
                   CAST((COALESCE(SUM(material_cost), 0) + COALESCE(SUM(labour_cost), 0)) AS DOUBLE PRECISION) AS total_cost
            FROM rework_events
            {where}
            GROUP BY reason ORDER BY entries DESC LIMIT %(limit)s
            """,
            {"since": db.nz_now().date() - timedelta(days=days or 0), "limit": limit},
        )
        return cur.fetchall()


def by_door_type(limit: int = 10, days: int | None = 90) -> list[dict]:
    where = "WHERE rework_date >= %(since)s" if days is not None else ""
    with db.get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            f"""
            SELECT door_type, COUNT(*) AS entries
            FROM rework_events
            {where}
            GROUP BY door_type ORDER BY entries DESC LIMIT %(limit)s
            """,
            {"since": db.nz_now().date() - timedelta(days=days or 0), "limit": limit},
        )
        return cur.fetchall()


def by_colour(limit: int = 10, days: int | None = 90) -> list[dict]:
    where = "WHERE rework_date >= %(since)s" if days is not None else ""
    with db.get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            f"""
            SELECT colour, COUNT(*) AS entries
            FROM rework_events
            {where}
            GROUP BY colour ORDER BY entries DESC LIMIT %(limit)s
            """,
            {"since": db.nz_now().date() - timedelta(days=days or 0), "limit": limit},
        )
        return cur.fetchall()
