"""Consistent online SQLite backup; safe while the application is serving requests."""

from datetime import datetime, timedelta, timezone
from contextlib import closing
import os
from pathlib import Path
import sqlite3


def backup_database(source: Path, directory: Path) -> Path:
    source = source.resolve()
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    destination = directory / f"rework-{stamp}.sqlite3"
    partial = destination.with_suffix(".partial")
    try:
        with closing(sqlite3.connect(source.as_uri() + "?mode=ro", uri=True)) as live:
            snapshot = sqlite3.connect(partial)
            try:
                live.backup(snapshot, pages=256)
                result = snapshot.execute("PRAGMA integrity_check").fetchone()[0]
                if result != "ok":
                    raise RuntimeError(f"SQLite backup integrity check failed: {result}")
            finally:
                snapshot.close()
        os.chmod(partial, 0o600)
        partial.replace(destination)
    finally:
        partial.unlink(missing_ok=True)
    return destination


def main():
    os.umask(0o077)
    source = Path(os.getenv("SQLITE_PATH", "data/rework.sqlite3"))
    directory = source.parent / "backups"
    result = backup_database(source, directory)
    cutoff = (datetime.now(timezone.utc) - timedelta(days=7)).timestamp()
    for path in directory.glob("rework-*.sqlite3"):
        if path.stat().st_mtime < cutoff:
            path.unlink()
    print(f"Backup saved and integrity checked: {result}")


if __name__ == "__main__":
    main()
