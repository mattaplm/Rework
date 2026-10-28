"""Admin-only page to re-upload the rework spreadsheet at any time while it's
still in parallel use -- wraps the same services.rework_import used by the
one-off historical backfill, so repeated uploads are always safe (already-
imported rows are skipped by their content hash, never duplicated).

Also handles the turret workbooks ('Turret Sheet Audit YYYY.xlsx') the same
way -- added 2026-10-28 so a re-import doesn't require server console access
(services.turret_import was previously only reachable via
import_turret_log.py). Same dedup-by-hash safety, same two-layout split
(2024 vs. 2025/2026, see services/turret_import.py's docstring) exposed here
as a form field instead of a CLI argument."""

from __future__ import annotations

import os
import tempfile

from flask import Blueprint, render_template, request

from services import rework_import, turret_import
from services.auth import role_required

bp = Blueprint("import_excel", __name__)


@bp.route("/import", methods=["GET", "POST"])
@role_required("admin")
def import_page():
    result = None
    error = None
    turret_result = None
    turret_error = None

    if request.method == "POST":
        import_type = request.form.get("import_type", "rework")
        file = request.files.get("file")
        if not file or not file.filename:
            err_msg = "Choose a .xlsx file first."
            if import_type == "turret":
                turret_error = err_msg
            else:
                error = err_msg
        elif not file.filename.lower().endswith(".xlsx"):
            err_msg = "Must be a .xlsx file."
            if import_type == "turret":
                turret_error = err_msg
            else:
                error = err_msg
        else:
            fd, tmp_path = tempfile.mkstemp(suffix=".xlsx")
            try:
                os.close(fd)
                file.save(tmp_path)
                if import_type == "turret":
                    layout = request.form.get("layout", "current")
                    try:
                        turret_result = turret_import.import_workbook(tmp_path, layout=layout)
                    except KeyError:
                        turret_error = "Couldn't find 'Sheet1' in that file -- is this the right workbook?"
                else:
                    try:
                        result = rework_import.import_workbook(tmp_path)
                    except KeyError:
                        error = "Couldn't find a 'REWORK' sheet in that file -- is this the right workbook?"
            finally:
                os.remove(tmp_path)

    return render_template(
        "import_excel.html",
        active="import",
        result=result,
        error=error,
        turret_result=turret_result,
        turret_error=turret_error,
    )
