"""Create private first-install settings without overwriting an existing deployment."""

import os
from pathlib import Path
import secrets


def main():
    target = Path(__file__).resolve().parent / ".env"
    (target.parent / "data").mkdir(mode=0o700, exist_ok=True)
    values = {
        "REWORK_IMAGE": "rework:aplmapps01-sqlite-20261028",
        "REWORK_BIND": "10.160.21.109",
        "REWORK_PORT": "5071",
        "DATABASE_BACKEND": "sqlite",
        "SQLITE_PATH": "/data/rework.sqlite3",
        "SECRET_KEY": secrets.token_hex(32),
        "ADMIN_DEFAULT_PASSWORD": f"{secrets.randbelow(10000):04d}",
        "SQL_SERVER": "",
        "SQL_DATABASE": "",
        "SQL_USERNAME": "",
        "SQL_PASSWORD": "",
        "SQL_DRIVER": "{ODBC Driver 17 for SQL Server}",
    }
    try:
        fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        print("Existing .env retained; no credentials changed.")
        return
    with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
        stream.writelines(f"{key}={value}\n" for key, value in values.items())
    print("Created private .env for SQLite storage.")
    print("The initial admin PIN is ADMIN_DEFAULT_PASSWORD.")


if __name__ == "__main__":
    main()
