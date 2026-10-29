"""Deploy new pushes to main as the existing app owner; run once per minute."""

from contextlib import contextmanager
import logging
from logging.handlers import RotatingFileHandler
import os
from pathlib import Path
import shutil
import subprocess
import tarfile
import tempfile


REPOSITORY = "https://github.com/mattaplm/Rework.git"
LOG = logging.getLogger("rework-deploy")


def run(*args, cwd=None, env=None, timeout=900):
    result = subprocess.run(args, cwd=cwd, env=env, text=True,
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            timeout=timeout)
    if result.stdout.strip():
        LOG.info("%s", result.stdout.rstrip())
    result.check_returncode()
    return result.stdout.strip()


def atomic_write(path, value):
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(value, encoding="utf-8")
    temporary.replace(path)


def persist_image(env_file, image):
    lines = env_file.read_text(encoding="utf-8").splitlines()
    lines = [line for line in lines if not line.startswith("REWORK_IMAGE=")]
    atomic_write(env_file, "\n".join([*lines, f"REWORK_IMAGE={image}", ""]))


def unpack_source(archive, source):
    source.mkdir()
    with tarfile.open(archive) as bundle:
        bundle.extractall(source, filter="data")
    # The data filter leaves directory modes to umask (077 for private host
    # state). Docker COPY preserves those modes but makes files root-owned,
    # so the non-root app needs readable/traversable source directories.
    # The enclosing temporary release directory remains private on the host.
    source.chmod(0o755)
    for path in source.rglob("*"):
        if path.is_dir():
            path.chmod(0o755)


def deploy(root, state):
    if (state / "paused").exists():
        return
    repository = state / "repository.git"
    if not repository.exists():
        run("git", "init", "--bare", str(repository))
    run("git", "-C", str(repository), "fetch", "--quiet", "--depth=1",
        REPOSITORY, "refs/heads/main", timeout=120)
    revision = run("git", "-C", str(repository), "rev-parse", "FETCH_HEAD", timeout=30)
    for marker in ("deployed", "failed"):
        path = state / marker
        if path.exists() and path.read_text().strip() == revision:
            return

    LOG.info("Preparing revision %s", revision)
    try:
        with tempfile.TemporaryDirectory(prefix="release-", dir=state) as directory:
            release = Path(directory)
            archive = release / "source.tar"
            run("git", "-C", str(repository), "archive", "--format=tar",
                f"--output={archive}", revision)
            source = release / "source"
            unpack_source(archive, source)
            # main originally contained only PostgreSQL support. Never deploy it
            # over the hosted SQLite app before the hosting changes are published.
            for required in ("sqlite_db.py", "backup_sqlite.py", ".dockerignore",
                             "migrations/sqlite/0001_init.sql"):
                if not (source / required).is_file():
                    raise RuntimeError(f"Release is missing required SQLite hosting file: {required}")
            image = f"rework:git-{revision}"
            run("docker", "build", "--label", f"org.opencontainers.image.revision={revision}",
                "--tag", image, str(source), timeout=1200)
            run("docker", "run", "--rm", "--user", "0:0",
                "--mount", f"type=bind,src={source / 'tests'},dst=/tests,readonly",
                "--mount", f"type=bind,src={source / 'deploy'},dst=/deploy,readonly",
                "--entrypoint", "sh", image, "-ec",
                "pip install --quiet pytest && python -m pytest /tests -q -p no:cacheprovider",
                timeout=300)

            compose = ("docker", "compose", "--project-directory", str(root),
                       "--file", str(root / "compose.yml"))
            # The backup uses SQLite's online API while the old app keeps serving.
            run(*compose, "exec", "-T", "app", "python", "backup_sqlite.py")
            backups = sorted((root / "data" / "backups").glob("rework-*.sqlite3"))
            if not backups:
                raise RuntimeError("No database backup was produced; deployment stopped.")
            probe = release / "probe"
            probe.mkdir()
            shutil.copy2(backups[-1], probe / "rework.sqlite3")
            # Exercise new migrations and Flask against a COPY of the real data.
            # No ERP network access, scheduled syncs, or production secrets here.
            run("docker", "run", "--rm", "--network", "none",
                "--user", f"{os.getuid()}:{os.getgid()}",
                "--mount", f"type=bind,src={probe},dst=/data",
                "--env", "DATABASE_BACKEND=sqlite", "--env", "SQLITE_PATH=/data/rework.sqlite3",
                "--env", "SECRET_KEY=deployment-probe", image, "python", "-c",
                "from services import scheduled_sync; "
                "scheduled_sync.start_background_thread = lambda: None; "
                "from app import app; "
                "assert app.test_client().get('/login').status_code == 200",
                timeout=180)

            # Refuse stale deployments if another push arrived during the build.
            latest = run("git", "ls-remote", REPOSITORY, "refs/heads/main", timeout=120)
            if latest.split()[0] != revision:
                LOG.info("A newer push arrived; the next run will build it.")
                return
            env = dict(os.environ, REWORK_IMAGE=image)
            try:
                run(*compose, "up", "-d", "--wait", "--wait-timeout", "180", "app",
                    env=env, timeout=240)
            except (subprocess.SubprocessError, OSError):
                LOG.exception("New container failed; restarting the previously configured image")
                # Keep the database and its backup. Never restore data automatically:
                # that could erase writes accepted during the health-check window.
                run(*compose, "up", "-d", "--wait", "--wait-timeout", "180", "app", timeout=240)
                raise
            persist_image(root / ".env", image)
            atomic_write(state / "deployed", revision + "\n")
            (state / "failed").unlink(missing_ok=True)
            LOG.info("Successfully deployed %s", revision)
    except Exception:
        atomic_write(state / "failed", revision + "\n")
        raise


@contextmanager
def deployment_lock(state):
    import fcntl  # Linux host only; keep helper functions testable on Windows.

    with (state / "lock").open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            yield False
            return
        yield True


def main():
    os.umask(0o077)
    root = Path(__file__).resolve().parent
    state = root / ".autodeploy"
    state.mkdir(mode=0o700, exist_ok=True)
    LOG.setLevel(logging.INFO)
    handler = RotatingFileHandler(state / "deploy.log", maxBytes=2_000_000, backupCount=3)
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    LOG.addHandler(handler)
    with deployment_lock(state) as acquired:
        if acquired:
            try:
                deploy(root, state)
            except Exception:
                LOG.exception("Deployment failed; see above. Remove .autodeploy/failed to retry this revision.")
                return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
