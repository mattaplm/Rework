import importlib
import sqlite3

import pytest

import db
from services import scheduled_sync


@pytest.fixture
def health_client(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_BACKEND", "sqlite")
    monkeypatch.setenv("SQLITE_PATH", str(tmp_path / "health.sqlite3"))
    monkeypatch.setenv("ADMIN_DEFAULT_PASSWORD", "6543")
    monkeypatch.setenv("REWORK_REVISION", "a" * 40)
    monkeypatch.setattr(scheduled_sync, "start_background_thread", lambda: None)
    module = importlib.import_module("app")
    application = module.create_app()
    return application.test_client()


def test_health_reports_revision_without_authentication(health_client):
    response = health_client.get("/health")
    assert response.status_code == 200
    assert response.json == {"status": "ok", "revision": "a" * 40}


def test_health_does_not_report_success_when_database_fails(health_client, monkeypatch):
    def unavailable():
        raise sqlite3.OperationalError("Database unavailable")

    monkeypatch.setattr(db, "get_conn", unavailable)
    assert health_client.get("/health").status_code == 500
