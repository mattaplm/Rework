import importlib.util
from pathlib import Path
import subprocess
import tarfile

import pytest


spec = importlib.util.spec_from_file_location(
    "auto_deploy", Path(__file__).resolve().parents[1] / "deploy/aplmapps01/auto_deploy.py")
auto_deploy = importlib.util.module_from_spec(spec)
spec.loader.exec_module(auto_deploy)
REVISION = "a" * 40


@pytest.fixture
def deployment(tmp_path, monkeypatch):
    root = tmp_path / "host"
    state = root / ".autodeploy"
    state.mkdir(parents=True)
    (root / ".env").write_text("SECRET_KEY=keep-me\nREWORK_IMAGE=rework:previous\n")
    (root / "data/backups").mkdir(parents=True)
    live = root / "data/rework.sqlite3"
    live.write_bytes(b"live database must not be replaced")
    source = tmp_path / "source"
    for name in ("sqlite_db.py", "backup_sqlite.py", ".dockerignore",
                 "migrations/sqlite/0001_init.sql", "tests/test_example.py"):
        file = source / name
        file.parent.mkdir(parents=True, exist_ok=True)
        file.touch()
    calls = []

    def run(*args, **kwargs):
        calls.append((args, kwargs))
        if "rev-parse" in args:
            return REVISION
        if "ls-remote" in args:
            return f"{REVISION}\trefs/heads/main"
        if "archive" in args:
            output = next(arg.removeprefix("--output=") for arg in args if arg.startswith("--output="))
            with tarfile.open(output, "w") as bundle:
                bundle.add(source, arcname=".")
        if "exec" in args:
            (root / "data/backups/rework-20261029T000000Z.sqlite3").write_bytes(b"snapshot")
        return ""

    monkeypatch.setattr(auto_deploy, "run", run)
    monkeypatch.setattr(auto_deploy.os, "getuid", lambda: 1001, raising=False)
    monkeypatch.setattr(auto_deploy.os, "getgid", lambda: 1001, raising=False)
    return root, state, source, calls, run


def test_success_backs_up_and_probes_before_updating_image(deployment):
    root, state, source, calls, _ = deployment
    auto_deploy.deploy(root, state)
    assert (state / "deployed").read_text().strip() == REVISION
    assert (root / ".env").read_text() == f"SECRET_KEY=keep-me\nREWORK_IMAGE=rework:git-{REVISION}\n"
    assert (root / "data/rework.sqlite3").read_bytes() == b"live database must not be replaced"
    commands = [args for args, _ in calls]
    backup = next(i for i, args in enumerate(commands) if "exec" in args)
    probe = next(i for i, args in enumerate(commands) if "none" in args)
    switch = next(i for i, args in enumerate(commands) if "up" in args)
    assert backup < probe < switch
    assert not list(state.glob("release-*"))


@pytest.mark.parametrize("marker", ["deployed", "failed", "paused"])
def test_known_or_paused_revision_does_not_redeploy(deployment, marker):
    root, state, _, calls, _ = deployment
    (state / marker).write_text(REVISION)
    auto_deploy.deploy(root, state)
    assert not any(args[0] == "docker" for args, _ in calls)


def test_missing_hosting_support_cannot_replace_sqlite_app(deployment):
    root, state, source, calls, _ = deployment
    (source / "sqlite_db.py").unlink()
    with pytest.raises(RuntimeError, match="missing required SQLite"):
        auto_deploy.deploy(root, state)
    assert not any(args[0] == "docker" for args, _ in calls)
    assert (state / "failed").read_text().strip() == REVISION


@pytest.mark.parametrize("failure_stage", ["build", "probe", "switch"])
def test_failure_keeps_previous_configuration_and_live_data(deployment, monkeypatch, failure_stage):
    root, state, _, calls, original = deployment

    def fail(*args, **kwargs):
        result = original(*args, **kwargs)
        if ((failure_stage == "build" and "build" in args)
                or (failure_stage == "probe" and "none" in args)
                or (failure_stage == "switch" and "up" in args and kwargs.get("env"))):
            raise subprocess.CalledProcessError(1, args)
        return result

    monkeypatch.setattr(auto_deploy, "run", fail)
    with pytest.raises(subprocess.CalledProcessError):
        auto_deploy.deploy(root, state)
    assert (root / ".env").read_text() == "SECRET_KEY=keep-me\nREWORK_IMAGE=rework:previous\n"
    assert (root / "data/rework.sqlite3").read_bytes() == b"live database must not be replaced"
    assert not (state / "deployed").exists()
    assert (state / "failed").read_text().strip() == REVISION
    switches = [(args, kwargs) for args, kwargs in calls if "up" in args]
    if failure_stage == "switch":
        assert len(switches) == 2
        assert not switches[-1][1].get("env")
    else:
        assert not switches
    assert not list(state.glob("release-*"))


def test_newer_push_skips_outdated_release(deployment, monkeypatch):
    root, state, _, calls, original = deployment

    def newer(*args, **kwargs):
        if "ls-remote" in args:
            return f"{'b' * 40}\trefs/heads/main"
        return original(*args, **kwargs)

    monkeypatch.setattr(auto_deploy, "run", newer)
    auto_deploy.deploy(root, state)
    assert not any("up" in args for args, _ in calls)
    assert not (state / "deployed").exists()
    assert not (state / "failed").exists()
