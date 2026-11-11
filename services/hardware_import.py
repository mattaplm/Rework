"""Importer for the Hardware workbook ('Scrap Rework - Use this one V2.xlsx',
2026-11-11). Three tabs, all in one upload:

  DATA VALIDATION, columns D/E -> hw_reasons (reason + Scrap Y/N); only
                                   reasons not already listed are added.
  Data Sheet, columns A-F       -> hw_parts (part, unit cost, supplier,
                                   product, material, material cost per unit);
                                   only parts not already listed are added --
                                   once a part is here, Hardware Admin owns it.
                                   The sheet has a few repeated part numbers;
                                   the first wins, same as its VLOOKUPs.
  Master Data Sheet             -> hw_events, keeping the sheet's own cached
                                   cost figures (not recomputed from today's
                                   parts list, same rule as Doors' import).

Matching rows across re-uploads: unlike the Doors/Turret workbooks, a row in
this sheet keeps changing after it's entered (Co-create, Pick and Complete
dates get filled in as the remake progresses, and Status follows them). So
the dedup hash covers only the columns set when the row is first entered --
SO, job, part, qty, colour, location, request date, reason. A re-upload then
refreshes the progress columns on rows already imported, *unless* the row
has since been edited in the app (`updated_at` set): from then on the app's
version wins. Identical rows within one file get a suffixed hash, same rule
as services/rework_import.py.

Powdercoat / Assembly names seen at least `MIN_NAME_USES` times (after
splitting combined entries like "IMTIYAAZ/AMZ") are added to those admin
lists, so one-off typos ("FERNADNO") don't end up in the dropdowns. The
rows themselves keep the sheet's text exactly.
"""

from __future__ import annotations

import hashlib
from collections import Counter
from dataclasses import dataclass, field
from datetime import date, datetime

import openpyxl

import db
from services.hardware import derive_status

MASTER_SHEET = "Master Data Sheet"
PARTS_SHEET = "Data Sheet"
REASONS_SHEET = "DATA VALIDATION"
MIN_NAME_USES = 3

COL = dict(status=0, so_number=1, job_number=2, part_number=3, quantity=4, colour=5,
           colour_code=6, location=7, request_date=8, cocreate_date=9, pick_date=10,
           complete_date=11, reason=12, scrap=13, powdercoater=14, comments=15, assembler=16,
           product_code=17, material=18, unit_cost=19, scrap_cost=20, material_cost=21,
           material_scrap_cost=22, supplier=23)
IDENTITY = ("so_number", "job_number", "part_number", "quantity", "colour", "location",
            "request_date", "reason")
PROGRESS = ("status", "cocreate_date", "pick_date", "complete_date", "powdercoater",
            "assembler", "comments")
_STATUS = {"closed": "Closed", "open": "Open", "log job": "Log Job", "scrap": "Scrap"}
_MATERIAL = {"zinc": "Zinc", "ali": "Ali"}
_ERROR_CELLS = {"#N/A", "#REF!", "#VALUE!", "#DIV/0!"}


@dataclass
class ImportResult:
    reasons_added: int = 0
    parts_added: int = 0
    people_added: int = 0
    inserted: int = 0
    updated: int = 0
    unchanged: int = 0
    skipped_invalid: int = 0
    invalid_examples: list[str] = field(default_factory=list)


def _str(v) -> str | None:
    if v is None or isinstance(v, bool):
        return None
    if isinstance(v, float) and v.is_integer():
        v = int(v)
    text = " ".join(str(v).split())
    return None if text in ("", "0") or text in _ERROR_CELLS else text


def _num(v) -> float | None:
    return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else None


def _cents(v) -> float | None:
    number = _num(v)
    return round(number, 2) if number is not None else None


def _date(v) -> date | None:
    if isinstance(v, datetime):
        return v.date()
    return v if isinstance(v, date) else None


def _hash(values) -> str:
    text = "|".join("" if v is None else str(v) for v in values)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _clean(row: tuple, reason_scrap: dict[str, bool]) -> dict | None:
    get = lambda key: row[COL[key]] if len(row) > COL[key] else None  # noqa: E731
    part = _str(get("part_number"))
    quantity = _num(get("quantity"))
    values = {
        "so_number": _str(get("so_number")),
        "job_number": _str(get("job_number")),
        "part_number": part.upper() if part else None,
        "quantity": int(quantity) if quantity is not None else None,
        "colour": _str(get("colour")),
        "colour_code": None if isinstance(get("colour_code"), datetime) else _str(get("colour_code")),
        "location": (_str(get("location")) or "").upper() or None,
        "request_date": _date(get("request_date")),
        "cocreate_date": _date(get("cocreate_date")),
        "pick_date": _date(get("pick_date")),
        "complete_date": _date(get("complete_date")),
        "reason": _str(get("reason")),
        "powdercoater": _str(get("powdercoater")),
        "assembler": _str(get("assembler")),
        "comments": _str(get("comments")),
        "product_code": (_str(get("product_code")) or "").upper() or None,
        "material": _MATERIAL.get((_str(get("material")) or "").lower(), _str(get("material"))),
        "supplier": _str(get("supplier")),
        "unit_cost": _num(get("unit_cost")),
        "material_cost": _num(get("material_cost")),
        "scrap_cost": _cents(get("scrap_cost")),
        "material_scrap_cost": _cents(get("material_scrap_cost")),
    }
    if not values["request_date"] or not values["part_number"] or not values["quantity"]:
        return None

    scrap_cell = (_str(get("scrap")) or "").lower()
    if scrap_cell in ("yes", "no"):
        values["is_scrap"] = scrap_cell == "yes"
    else:  # #N/A in the sheet: its reason wasn't in DATA VALIDATION at the time
        values["is_scrap"] = reason_scrap.get((values["reason"] or "").upper(), False)

    status = _STATUS.get((_str(get("status")) or "").lower())
    values["status"] = status or derive_status(values["pick_date"], values["complete_date"], False)
    return values


def _identity(row: tuple) -> tuple:
    return tuple(row[COL[k]] if len(row) > COL[k] else None for k in IDENTITY)


def _import_reasons(cur, wb, result: ImportResult) -> dict[str, bool]:
    cur.execute("SELECT reason, is_scrap FROM hw_reasons")
    known = {r["reason"].upper(): bool(r["is_scrap"]) for r in cur.fetchall()}
    cur.execute("SELECT COALESCE(MAX(sort_order), 0) AS n FROM hw_reasons")
    sort_order = cur.fetchone()["n"]
    if REASONS_SHEET in wb.sheetnames:
        for row in wb[REASONS_SHEET].iter_rows(min_row=2, values_only=True):
            reason = _str(row[3]) if len(row) > 3 else None
            if not reason or reason.upper() in known:
                continue
            is_scrap = (_str(row[4]) or "").lower() == "yes" if len(row) > 4 else True
            sort_order += 1
            cur.execute("INSERT INTO hw_reasons (reason, is_scrap, sort_order) VALUES (%s, %s, %s)",
                        (reason, is_scrap, sort_order))
            known[reason.upper()] = is_scrap
            result.reasons_added += 1
    return known


def _import_parts(cur, wb, result: ImportResult) -> None:
    if PARTS_SHEET not in wb.sheetnames:
        return
    seen = set()
    for row in wb[PARTS_SHEET].iter_rows(min_row=2, values_only=True):
        part = _str(row[0]) if row else None
        if not part or part.upper() in seen:
            continue
        seen.add(part.upper())
        material = _str(row[4]) if len(row) > 4 else None
        cur.execute(
            "INSERT INTO hw_parts (part_number, unit_cost, supplier, product_code, material, material_cost) "
            "VALUES (%s, %s, %s, %s, %s, %s) ON CONFLICT (part_number) DO NOTHING RETURNING part_number",
            (part.upper(), _num(row[1]), _str(row[2]), (_str(row[3]) or "").upper() or None,
             _MATERIAL.get((material or "").lower(), material),
             _num(row[5]) if len(row) > 5 else None),
        )
        if cur.fetchone():
            result.parts_added += 1


def _import_people(cur, counts: dict[str, Counter], result: ImportResult) -> None:
    for column, table in (("powdercoater", "hw_powdercoaters"), ("assembler", "hw_assemblers")):
        cur.execute(f"SELECT name FROM {table}")
        known = {r["name"].upper() for r in cur.fetchall()}
        for name, uses in sorted(counts[column].items()):
            if uses < MIN_NAME_USES or name.upper() in known:
                continue
            cur.execute(f"INSERT INTO {table} (name) VALUES (%s)", (name,))
            known.add(name.upper())
            result.people_added += 1


def import_workbook(xlsx_path: str) -> ImportResult:
    result = ImportResult()
    wb = openpyxl.load_workbook(xlsx_path, data_only=True, read_only=True)
    try:
        if MASTER_SHEET not in wb.sheetnames:
            raise KeyError(MASTER_SHEET)
        with db.get_conn() as conn, conn.cursor() as cur:
            reason_scrap = _import_reasons(cur, wb, result)
            _import_parts(cur, wb, result)

            names: dict[str, Counter] = {"powdercoater": Counter(), "assembler": Counter()}
            seen_in_file: dict[str, int] = {}
            columns = list(PROGRESS) + [
                "so_number", "job_number", "part_number", "quantity", "colour", "colour_code",
                "location", "request_date", "reason", "is_scrap", "product_code", "material",
                "supplier", "unit_cost", "material_cost", "scrap_cost", "material_scrap_cost"]
            insert_sql = (f"INSERT INTO hw_events ({', '.join(columns)}, source_row_hash) VALUES ("
                          + ", ".join(f"%({c})s" for c in columns) + ", %(row_hash)s)")

            for raw in wb[MASTER_SHEET].iter_rows(min_row=2, values_only=True):
                if not any(v not in (None, "") for v in raw[:COL["supplier"] + 1]):
                    continue  # trailing blank rows
                cleaned = _clean(raw, reason_scrap)
                if cleaned is None:
                    result.skipped_invalid += 1
                    if len(result.invalid_examples) < 10:
                        result.invalid_examples.append(str(raw[:13]))
                    continue
                for column in names:
                    for name in (cleaned[column] or "").split("/"):
                        if name.strip():
                            names[column][name.strip().upper()] += 1

                row_hash = _hash(_identity(raw))
                seen_in_file[row_hash] = seen_in_file.get(row_hash, 0) + 1
                if seen_in_file[row_hash] > 1:
                    row_hash = _hash((row_hash, seen_in_file[row_hash]))

                cur.execute("SELECT id, updated_at, " + ", ".join(PROGRESS)
                            + " FROM hw_events WHERE source_row_hash = %s", (row_hash,))
                existing = cur.fetchone()
                if existing is None:
                    cur.execute(insert_sql, {**cleaned, "row_hash": row_hash})
                    result.inserted += 1
                elif existing["updated_at"] is None and any(existing[c] != cleaned[c] for c in PROGRESS):
                    cur.execute("UPDATE hw_events SET " + ", ".join(f"{c} = %({c})s" for c in PROGRESS)
                                + " WHERE id = %(id)s", {**cleaned, "id": existing["id"]})
                    result.updated += 1
                else:
                    result.unchanged += 1

            _import_people(cur, names, result)
    finally:
        wb.close()
    return result
