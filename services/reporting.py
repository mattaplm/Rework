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

import db


def summary(days: int | None = 90) -> dict:
    where = "WHERE rework_date >= CURRENT_DATE - make_interval(days => %(days)s)" if days is not None else ""
    with db.get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            f"""
            SELECT
                COUNT(*) AS total_entries,
                (COALESCE(SUM(material_cost), 0) + COALESCE(SUM(labour_cost), 0))::float8 AS total_cost,
                COUNT(*) FILTER (WHERE type = 'Rework / Recoat') AS rework_count,
                COUNT(*) FILTER (WHERE type = 'Replace Part') AS replace_count,
                COUNT(*) FILTER (WHERE type = 'Scrap Entire Door') AS scrap_count
            FROM rework_events
            {where}
            """,
            {"days": days},
        )
        return cur.fetchone()


def weekly_trend(weeks: int | None = 12) -> list[dict]:
    where = "WHERE rework_date >= CURRENT_DATE - make_interval(weeks => %(weeks)s)" if weeks is not None else ""
    with db.get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            f"""
            SELECT date_trunc('week', rework_date)::date::text AS week_start,
                   COUNT(*) AS entries,
                   (COALESCE(SUM(material_cost), 0) + COALESCE(SUM(labour_cost), 0))::float8 AS total_cost
            FROM rework_events
            {where}
            GROUP BY 1 ORDER BY 1
            """,
            {"weeks": weeks},
        )
        return cur.fetchall()


def top_reasons(limit: int = 8, days: int | None = 90) -> list[dict]:
    where = "WHERE rework_date >= CURRENT_DATE - make_interval(days => %(days)s)" if days is not None else ""
    with db.get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            f"""
            SELECT reason, COUNT(*) AS entries,
                   (COALESCE(SUM(material_cost), 0) + COALESCE(SUM(labour_cost), 0))::float8 AS total_cost
            FROM rework_events
            {where}
            GROUP BY reason ORDER BY entries DESC LIMIT %(limit)s
            """,
            {"days": days, "limit": limit},
        )
        return cur.fetchall()


def by_door_type(limit: int = 10, days: int | None = 90) -> list[dict]:
    where = "WHERE rework_date >= CURRENT_DATE - make_interval(days => %(days)s)" if days is not None else ""
    with db.get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            f"""
            SELECT door_type, COUNT(*) AS entries
            FROM rework_events
            {where}
            GROUP BY door_type ORDER BY entries DESC LIMIT %(limit)s
            """,
            {"days": days, "limit": limit},
        )
        return cur.fetchall()


def by_colour(limit: int = 10, days: int | None = 90) -> list[dict]:
    where = "WHERE rework_date >= CURRENT_DATE - make_interval(days => %(days)s)" if days is not None else ""
    with db.get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            f"""
            SELECT colour, COUNT(*) AS entries
            FROM rework_events
            {where}
            GROUP BY colour ORDER BY entries DESC LIMIT %(limit)s
            """,
            {"days": days, "limit": limit},
        )
        return cur.fetchall()
