"""App factory for the Doors Rework tracker. Thin by design -- see Scheduler's
app.py for the same shape: load config, init the DB, register blueprints, go."""

from __future__ import annotations

import logging
import os

from dotenv import load_dotenv
from flask import Flask, request

import db
from blueprints import admin, auth, dashboard, import_excel, pages, rework, turret, users
from services import scheduled_sync
from services.auth import current_user, touch_current_session

load_dotenv()
logging.basicConfig(level=logging.INFO)


def create_app() -> Flask:
    app = Flask(__name__)
    app.secret_key = os.getenv("SECRET_KEY", "dev-secret-change-me")
    app.config["SESSION_COOKIE_HTTPONLY"] = True
    app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
    app.config["MAX_CONTENT_LENGTH"] = 64 * 1024 * 1024  # 64MB -- generous headroom over the current ~12MB workbook

    db.init_db()
    scheduled_sync.start_background_thread()

    app.register_blueprint(pages.bp)
    app.register_blueprint(auth.bp)
    app.register_blueprint(rework.bp)
    app.register_blueprint(turret.bp)
    app.register_blueprint(admin.bp)
    app.register_blueprint(users.bp)
    app.register_blueprint(import_excel.bp)
    app.register_blueprint(dashboard.bp)

    @app.get("/health")
    def health():
        with db.get_conn() as conn, conn.cursor() as cur:
            cur.execute("SELECT 1")
            cur.fetchone()
        return {"status": "ok", "revision": os.getenv("REWORK_REVISION", "development")}

    @app.context_processor
    def inject_user():
        return {"current_user": current_user()}

    @app.after_request
    def after_request(response):
        if not request.path.startswith("/static/"):
            touch_current_session()
        return response

    return app


app = create_app()

if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5050)
