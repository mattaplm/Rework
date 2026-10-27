"""Admin-only page to re-upload the rework spreadsheet at any time while it's
still in parallel use -- wraps the same services.rework_import used by the
one-off historical backfill, so repeated uploads are always safe (already-
imported rows are skipped by their content hash, never duplicated)."""

from __future__ import annotations

import os
import tempfile

from flask import Blueprint, render_template, request

from services import rework_import
from services.auth import role_required

bp = Blueprint("import_excel", __name__)


@bp.route("/import", methods=["GET", "POST"])
@role_required("admin")
def import_page():
    result = None
    error = None

    if request.method == "POST":
        file = request.files.get("file")
        if not file or not file.filename:
            error = "Choose a .xlsx file first."
        elif not file.filename.lower().endswith(".xlsx"):
            error = "Must be a .xlsx file."
        else:
            fd, tmp_path = tempfile.mkstemp(suffix=".xlsx")
            try:
                os.close(fd)
                file.save(tmp_path)
                try:
                    result = rework_import.import_workbook(tmp_path)
                except KeyError:
                    error = "Couldn't find a 'REWORK' sheet in that file -- is this the right workbook?"
            finally:
                os.remove(tmp_path)

    return render_template("import_excel.html", active="import", result=result, error=error)
