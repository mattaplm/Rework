# Rework on APLMAPPS01

Live internal URL: http://aplmapps01:5071 (APL network/VPN).
Deployment directory: `/home/aplmadmin/rework`. Compose project: `rework`.
Container: `rework-app-1`. Automatic releases use image tags `rework:git-<commit>`.

The deployment runs one application container with SQLite. Its database lives
at `/home/aplmadmin/rework/data/rework.sqlite3`, mounted as `/data` in the app.
The directory belongs to `aplmadmin` and has mode 700. Compose runs the app as
UID/GID 1001 to match that owner. Configure `REWORK_UID`/`REWORK_GID` if moving
to another host. The app restarts automatically with Docker after a reboot.
Its memory limit is 512 MB. PostgreSQL is not started or required.

The app binds to `10.160.21.109:5071` only. This is an internal HTTP address;
use the APL network/VPN. Host nginx and other applications are unchanged.

## Verified on 2026-10-28

The login page is reachable from the client PC and collaborative browser.
Hosted authentication, PIN-change redirect, dashboard, rework/turret lists and
forms, Admin, and Excel import page passed HTTP checks. The same database file
survived container recreation. SQLite integrity checks and online backups pass.
Eleven automated tests passed, covering transactions, concurrent writes, foreign
keys, reporting/ISO weeks, Excel deduplication, ERP upserts, auth and restore.

The database started fresh. No historical rework or turret entries were imported.
ERP sync has populated items, colours, open-order caches and scrap transactions
using the supplied read-only SQL credentials and Linux ODBC driver.

Log in as `admin`. The initial PIN is `ADMIN_DEFAULT_PASSWORD` in the private
server `.env`, also saved in the ignored local project `.env` for handoff.
Change it on first login. Historical records can be imported through Admin's
Excel import page later; reference data can be managed in Admin or seeded
with `seed_reference_data.py` from the department's workbook.

## Configuration

The server's mode-600 `.env` contains deployment settings, session secret, initial
PIN and `SQL_*` ERP credentials. Never commit it or include it in an image.
`initialize.py` creates first-install settings and the private data directory;
it preserves an existing `.env`. Compose explicitly sets:

```dotenv
DATABASE_BACKEND=sqlite
SQLITE_PATH=/data/rework.sqlite3
```

The Linux image uses `SQL_DRIVER={ODBC Driver 17 for SQL Server}`. The original
Windows `{SQL Server}` driver name cannot be used inside this container.

The image excludes credentials, local databases, workbooks and caches. The
Debian Bookworm base matches the Microsoft ODBC repository. `openpyxl` is a
runtime dependency for the Excel upload handler.

## Backups and maintenance

Backups run daily at **02:45 in the server's Pacific/Auckland timezone**, through
the deployment owner's crontab entry marked `rework-sqlite-backup`. They use
SQLite's online backup API, verify integrity, and retain seven days of snapshots
under `data/backups/`. Backup output goes to `data/backups/backup.log`.
These snapshots share the application host; off-host backup is not configured.
Do not copy the live database file alone: SQLite uses WAL sidecar files.

```sh
cd /home/aplmadmin/rework
docker compose ps
docker compose exec -T app python backup_sqlite.py
docker compose logs --tail=100
```

Startup logs can contain the initial admin PIN; treat them as private.
For normal updates, push or merge to GitHub's `main` branch; see automatic
deployment below. Preserve `.env` and `data/` when transferring source or
configuration. SQLite schema changes are tracked separately under
`migrations/sqlite/` and run on app startup.

For recovery, stop this app, retain the current database and its WAL/SHM files,
and restore an integrity-checked snapshot as `data/rework.sqlite3`. Move the
old WAL/SHM files aside with the old database before starting the restored one;
keep ownership and permissions consistent. Never overwrite a running database.

`docker compose down` stops this app and preserves the host data directory.
PostgreSQL support remains available via `DATABASE_BACKEND=postgres` for a
future migration; switching backends does not transfer data automatically.

## Automatic deployment

`auto_deploy.py` checks `https://github.com/mattaplm/Rework.git` branch `main`
every minute through the application owner's crontab (`rework-auto-deploy`).
Local commits and pushes to feature branches do not deploy. A push to `main`
is normally picked up within one minute, followed by build/test/startup time.
The repository is public, so fetching it needs no GitHub credential.

The existing GitHub runner remains restricted and is not used for deployments.
The deployment job runs as `aplmadmin`, which already owns this application and
has Docker access. No sudo, new SSH key, or runner permission change is needed.

Each release builds an image tagged and labelled with the exact commit, runs
pytest in a disposable container, takes an online SQLite backup, and checks
migrations and `/login` against a copy of that backup with network access
disabled. Only then does it replace the app container and wait for health.
It persists `REWORK_IMAGE` and `.autodeploy/deployed` after success. The server's
private `.env`, persistent data and existing Compose configuration are retained.
Changes to Compose or the deployment agent require an explicit installation;
they are not applied by an application push.

Install or update the agent by copying `auto_deploy.py` and
`install-auto-deploy.sh` into a staging directory on APLMAPPS01, then running
`bash install-auto-deploy.sh` as `aplmadmin`. The installer preserves all other
crontab entries, including the nightly backup. Python 3.12+, Git, Docker Compose
with `--wait`, and outbound access to GitHub, package repositories and container
registries are required. The server already has these tools.

```sh
cd /home/aplmadmin/rework
cat .autodeploy/deployed                 # last successfully deployed commit
tail -n 80 .autodeploy/deploy.log         # rotating deployment log
touch .autodeploy/paused                 # pause future deployments
rm .autodeploy/paused                    # resume
rm .autodeploy/failed                    # retry a failed commit after fixing its cause
python3 auto_deploy.py                   # check now; lock prevents overlapping runs
```

A failed build, test, backup or probe leaves the running app untouched. If the
replacement container fails health checks, the agent attempts to restart the
previous image and records the failed commit. It does not retry that same
commit until `failed` is removed; a newer commit is attempted automatically.
Database migrations are not automatically undone, and data is never restored
automatically. Incompatible migrations can require manual recovery from the
backup using the procedure above. Old release images are retained for recovery;
their disk usage should be reviewed during server maintenance.
