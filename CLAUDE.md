# CLAUDE.md

This file provides guidance to Claude Code when working with code in this repository.

## What this is

A Flask app replacing the Doors department's `2023-2026 Rework Data.xlsx` manual
rework/scrap log. Staff log a rework/scrap event (what happened, which door, which
part, why); the app costs it automatically from ERP (SyteLine) item data instead
of relying on hidden spreadsheet formulas, and will grow into the reporting and
ERP-reconciliation views the old pivot-table sheets covered.

Sister app: `../Scheduler` (same Doors department, same SyteLine ERP, same
architectural conventions). Match its style unless there's a specific reason not
to -- this app exists so the two eventually feel like one product, not two.

## Commands

```bash
# Local dev
python -m venv .venv && .venv/Scripts/activate   # Windows; `source .venv/bin/activate` elsewhere
pip install -r requirements-dev.txt
docker compose up -d postgres                     # Postgres only, for local dev against a real app process
python app.py                                      # Flask debug server, localhost:5050

# Tests
python -m pytest -q

# Full stack (app + postgres)
docker compose up --build

# One-off: seed reasons/door types/work centres/items out of the original
# spreadsheet, so the dropdowns aren't empty on a fresh DB (colours and a
# second item refresh come from sync_erp.py instead -- see below)
python seed_reference_data.py "path/to/2023-2026 Rework Data.xlsx"

# Pull items + colours from SyteLine (confirmed working against the real
# alpac_App server -- see "Reference data vs. the ERP" below)
python sync_erp.py
```

No lint/format command is configured.

### Local dev without Docker / without admin rights

Docker Desktop needs admin rights (and, on this machine, its WSL2 backend
doesn't come up at all) -- most dev machines in this department don't have
that. `devdb/` is a no-admin-rights stand-in: `@electric-sql/pglite` is
**real Postgres compiled to WASM** (not a reimplementation), and
`@electric-sql/pglite-socket` speaks the real Postgres wire protocol over a
plain TCP socket, so `psycopg2`/the app connect to it exactly as they would
to a real server -- this is what every migration/seed/API test in this
project has actually been run against, not a mock.

```bash
cd devdb && npm install                     # first time only
npm run db                                  # starts pglite-server on 127.0.0.1:5433
```

`devdb/package.json`'s `db` script sets `--max-connections=20` (raised from
the original `5` on 2026-10-22) -- `db.py`'s own pool alone is sized `1, 5`
(min, max), so a `--max-connections=5` server left **zero** headroom for
anything else: a second browser tab, a background script, or the
scheduled-sync thread all competing for the same 5-connection ceiling
Flask's pool could already exhaust by itself. This was the real cause of
most of the "`psycopg2.OperationalError`: connection ... refused" flakiness
hit repeatedly during this project's own development, not inherent PGlite
instability -- confirmed by reproducing it on demand (a one-off diagnostic
script failing to connect while the app server already held connections)
and then not seeing it recur after the limit was raised.

Then point `.env` at it: `POSTGRES_HOST=localhost`, `POSTGRES_PORT=5433`,
`POSTGRES_DB=postgres`, `POSTGRES_USER=postgres`, `POSTGRES_PASSWORD=postgres`
(pglite-server doesn't enforce auth -- any password works, these are just
placeholders). `devdb/data/` (the actual database files) and
`devdb/node_modules/` are gitignored; `devdb/package.json` is committed so
`npm install` reproduces the same two packages for anyone else without
Docker/admin rights.

This remains a **local dev convenience only**. The hosted deployment now uses
SQLite (2026-10-28); PostgreSQL remains an optional backend for development
or a later migration. See the SQLite hosting section below.

**If `npm install` fails with `UNABLE_TO_GET_ISSUER_CERT_LOCALLY`**: the
corporate network TLS-intercepts outbound HTTPS, and Node (unlike curl/git,
which read the Windows certificate store) doesn't trust the corporate root by
default. Export the Windows-trusted roots to a PEM file and point Node at it
for the install:

```powershell
$certs = @()
$certs += Get-ChildItem Cert:\LocalMachine\Root, Cert:\CurrentUser\Root, Cert:\LocalMachine\CA -ErrorAction SilentlyContinue
$outPath = "$env:TEMP\system-ca-bundle.pem"
foreach ($c in $certs) {
  Add-Content $outPath "-----BEGIN CERTIFICATE-----"
  Add-Content $outPath ([Convert]::ToBase64String($c.RawData, 'InsertLineBreaks'))
  Add-Content $outPath "-----END CERTIFICATE-----"
}
```
```bash
NODE_EXTRA_CA_CERTS="$env:TEMP/system-ca-bundle.pem" npm install
```
Reading the certificate store doesn't need admin rights -- only installing
into it does.

## Configuration

### SQLite hosting on APLMAPPS01 (2026-10-28)

The hosted deployment currently uses `DATABASE_BACKEND=sqlite` and
`SQLITE_PATH=/data/rework.sqlite3`, with the host's private `data/` directory
mounted persistently. It runs only the app container. PostgreSQL remains an
explicit alternative (`DATABASE_BACKEND=postgres`, the default for existing
development setups); neither database is automatically migrated into the other.
See `deploy/aplmapps01/README.md` for the live deployment and backup commands.

`sqlite_db.py` supplies dict rows, parameter binding, ISO date helpers, foreign
keys and transaction handling. SQL dialect expressions live in `db.py`;
SQLite has its own migration history under `migrations/sqlite/`. Its first
migration matches the final PostgreSQL schema through migration 0014.
`python backup_sqlite.py` uses SQLite's online backup API and verifies the result.
Do not copy a live WAL database file alone as a backup.

Copy `.env.example` to `.env`. Key variables:
- `POSTGRES_*` -- local Postgres connection. Runs in its own container via
  `docker-compose.yml`; moves to the department's own Postgres server later by
  changing `POSTGRES_HOST` only.
- `SQL_SERVER` / `SQL_DATABASE` / `SQL_USERNAME` / `SQL_PASSWORD` / `SQL_DRIVER`
  -- the SyteLine reports DB (`alpac_App`, same server Scheduler connects to).
  Leave blank to run with ERP sync disabled -- reference data then only has
  whatever `seed_reference_data.py` or an admin has entered by hand. This
  machine has no admin rights to install "ODBC Driver 17/18 for SQL Server"
  (what Scheduler's own default assumes), so `SQL_DRIVER` here is the legacy
  `{SQL Server}` driver instead -- it ships with Windows already and works
  fine; only set it to the newer driver name if that's actually installed.
- `SECRET_KEY` -- Flask session key; set this explicitly in any real deployment.
- `ADMIN_DEFAULT_PASSWORD` -- password for the bootstrap `admin` account created
  on first startup when `users` is empty; if unset, a random one-time password
  is generated and logged (search startup logs for "created default admin account").

## Architecture

**Layering**: identical split to Scheduler -- `blueprints/` holds route handlers,
`services/` holds framework-agnostic logic (plain dicts in/out, no Flask
objects), `db.py` is the only place that talks to Postgres directly.

```
services/
  auth.py             login/session helpers + role_required decorator
                        (direct port of Scheduler's services/auth.py)
  costing.py           pure cost-calculation functions, ported from the
                         Excel workbook's Cost/Cost2/Qty-to-Remove formulas
                         (see its module docstring for the original formulas)
  reference_data.py    reads for reasons/door types/work centres/colours/items
                         (the entry form's dropdowns + product-code lookup)
  rework.py             validates + creates rework_events rows; always
                          recomputes cost server-side, never trusts a client value
  erp_sync.py            pulls items/colours from SyteLine into Postgres --
                           triggered by sync_erp.py OR Admin -> SQL Connection
  admin_data.py            writes behind the Admin page's reference-data tabs
                             (reasons/door types/work centres/colours/items/
                             rates); services.reference_data stays read-only
                             (what the entry form uses)
  rework_import.py           shared by the one-off historical backfill and
                               the Admin -> Import from Excel page -- same
                               importer, safe to re-run any time (dedup by
                               content hash, see its own docstring)
  reporting.py                 read-only aggregate queries behind the Dashboard

blueprints/
  pages.py           "/" -> redirect to the log
  auth.py              login/logout/change-password
  rework.py               the log (list + new-entry form), plus its JSON API
                            (create, item search/lookup, cost preview)
  admin.py                  Admin page (SQL/ERP connection, reference-data CRUD)
  users.py                    user management API (direct port of Scheduler's
                                blueprints/users.py), separate from admin.py
                                same way Scheduler splits them
  import_excel.py               Admin -> Import from Excel upload page
  dashboard.py                    Dashboard (weekly trend, top reasons, cost
                                    summary, colour/door-type breakdowns)

erp.py       read-only pyodbc connection to SyteLine (separate from db.py,
              which only ever talks to this app's own Postgres)
queries.py   SyteLine SQL text, kept separate from erp.py -- same split as
              Scheduler's db.py vs. queries.py
```

**Database (`db.py`)**: Postgres via `psycopg2`, raw SQL, no ORM -- same
convention as Scheduler's SQLite `db.py`, just a different backend. Schema
lives in `migrations/*.sql`, applied in filename order by `init_db()` (tracked
in a `schema_migrations` table so each file runs exactly once); add a new
`NNNN_description.sql` file for any schema change rather than editing an
already-applied one.

**Reference data vs. the ERP**: `door_types`, `work_centres`, and
`rework_reasons` are admin-maintained only. `colours` and `items` are *also*
ERP-synced (`services/erp_sync.py`, run via `python sync_erp.py` -- confirmed
working live against `alpac_App`: pulls 5,223 active items from `item_mst`
and 500 colours from `emdaColour`, the exact same query Scheduler's own
Colour Library uses, so both apps' colour lists never drift apart). No
scheduled/admin-triggered sync yet -- it's a manual script for now (see "Not
yet done").

Column names were confirmed live, not guessed: `item_mst.unit_cost` matches
the old spreadsheet's "Std Cost" exactly, and `uf_emdaLength` is a real
per-item length field -- so lengths genuinely are available from the ERP as
originally described, though it's the item's own physical length, not the
same concept as the old Material masters sheet's family-grouped "Lengths
std/oversize". There's a separate length-charting subsystem
(`emdaLengthCharts`/`emdaLengths`/`emdaLengthChartKey`) that looked like a
plausible home for that family-grouped concept -- checked live against
`alpac_App` on 2026-10-20: all three tables exist but hold **zero rows**,
confirmed unused, nothing to wire up. `uf_emdaLength` is the only real
length data this ERP has. See `queries.py`'s module docstring for details.

`items.rule` (the units-per-part multiplier used for Qty to Remove) is
locally owned and survives a sync untouched, even though the rest of that
row's columns are ERP-owned -- same pattern as Scheduler's colour-rank sync
preserving manually-set rank/family across a re-sync (see Scheduler's
CLAUDE.md, "Configuration" section, `COLOUR_RANK_PATH`). `erp_sync.sync_items`
deliberately leaves `rule` out of its `UPDATE SET`, and `sync_colours`
deactivates (never deletes) a colour the ERP no longer returns, so a colour
already logged against never breaks.

**Cost calculation** (`services/costing.compute_costs`): ported from the
workbook's `Rework` table formula (M column, material cost -- see that
module's docstring). The entry form calls `/api/cost-preview` for live
feedback as the operator types; `services.rework.create_event` recomputes the
same thing server-side on save and is the only value that's ever stored --
the client-side number is a preview, never trusted input.

**Labour cost is on hold** (2026-10-20): the old sheet's "Cost 2" column
(per-part picking/cutting/machining/assembly rates × an hourly rate) isn't
computed for new entries, and the Admin page's old rate-management UI was
removed. `rework_events.labour_cost`, the `rework_rates` table and
`settings.hourly_rate` all stay in the schema untouched -- 11,961 historical
rows carry a real labour_cost from the spreadsheet import, and the Dashboard's
"Total cost" figure still sums it in where present, so that history isn't
lost or zeroed out. Only the *forward-looking* calculation and its admin UI
are gone; reviving it is a `services/costing.py` change (see git history for
the previous rate-based formula) plus rebuilding the Items & Rates admin tab.

**UI shell**: `templates/base.html` + `static/style.css` mirror Scheduler's
fixed left sidebar (brand block, `nav-section`/`nav-link`/`nav-label`,
collapsible on narrow screens via `#nav-toggle` + `body.nav-open`) rather than
a top bar, for visual/structural consistency between the two apps. Only real
pages get a nav entry; a muted `.nav-note` under the nav links says plainly
what isn't built yet instead of linking to something that doesn't exist.

**Performance**: `db.get_conn()` uses a pooled connection
(`psycopg2.pool.ThreadedConnectionPool`, 1-5 connections), not a fresh
`psycopg2.connect()` per call -- a single page load fires off several DB
calls (e.g. login alone does 4: look up the user, create the session, touch
last-login, prune old sessions), and opening a brand-new connection for each
one was the main reason the app felt slow. The *very first* request after a
process start still pays a one-time ~2s pool warm-up; every request after
that is sub-millisecond at the DB layer. `after_request`'s session-touch is
also skipped for `/static/*` so loading a page's CSS/JS doesn't itself write
to the DB.

**A live ERP query belongs behind its own route, never inlined into a page
route** (confirmed the hard way 2026-10-20): `admin_page()` briefly called
`erp_lookup.list_unmapped_cpq_codes()` directly so Door Codes could show
what's missing on load -- that query is an unindexed `DISTINCT` over all of
`coitem_all`, ~17 seconds against the real ERP, so *every* Admin page visit
took 17 seconds, not just the Door Codes tab. Moved to its own endpoint
(`/api/admin/door-codes/unmapped`) behind an explicit "Check SyteLine" button
instead -- the rule going forward: a route that renders a page should only
ever touch Postgres (fast, pooled); anything that calls `erp.fetch_all`
belongs in its own `/api/...` route triggered by a button, never inlined into
what loads when a page opens.

**Auth**: copied wholesale from Scheduler -- same `users`/`sessions` tables,
same server-side session validation (so deactivating a user or changing their
role takes effect immediately, not on next login), same hierarchical
viewer < operator < admin roles. Reading the log requires no particular role
beyond being logged in (unlike Scheduler, which allows anonymous reads --
there's no reason for this one to be visible off the network); creating an
entry requires `operator`.

**4-digit PIN auth, viewer accounts need none at all** (2026-10-22, replaces
free-text passwords): `services.auth.is_valid_pin` requires exactly 4 digits
for every operator/admin account -- enforced in `blueprints/users.py`'s
create/reset-password and `blueprints/auth.py`'s change-password flow.
`users.password_hash` now allows NULL (migration `0014`) -- a viewer account
can be created or reset with a blank PIN, stored as NULL, which `services.
auth.can_login_without_pin` treats as "log in on username alone": the login
form still has one shared PIN field for every role (no way to know a
username's role before it's typed), but whatever's in it is ignored for
that case. Confirmed live: a viewer account with no PIN logs in with an
empty password field; an operator/admin account still rejects a blank or
wrong PIN exactly as before -- this never weakens anything but the viewer
case specifically. A viewer *can* still be given a real PIN via Reset
Password if wanted; nothing forces the blank state. The bootstrap default
admin account (`db._ensure_default_admin`) now generates a 4-digit PIN
instead of a long random password when `ADMIN_DEFAULT_PASSWORD` is unset,
same policy.

**Audit Log** (`services/audit.py`, `audit_log` table, Admin -> Audit Log,
2026-10-22, requested as "full logging of entries and modifications and
logons by username"): every successful logon, every rework/turret entry
create (and turret's reopen-to-edit), and every Admin reference-data/user-
management/ERP-sync action writes one row -- `at`/`username`/`action`/
`entity_type`/`entity_id`/`detail` (`detail` a JSON-encoded string, not a
native Postgres jsonb column -- this project hasn't used jsonb anywhere
else, and a plain TEXT column sidesteps any question of whether PGlite's
jsonb support is complete for local dev). Confirmed live end-to-end: a
login, a user-create, a reset-password, a rework-event create, and a
reason activate/deactivate were each exercised and all five showed up
correctly in order. `services.audit.log` is called from the **blueprint**
layer only, never from `services/*.py` -- "who did this" is a web-session
concept (`services.auth.current_user()`), and keeping it out of the
framework-agnostic service layer matches this app's existing
services/blueprints split (see "Layering" above) rather than growing a
`username` parameter onto service functions that have no other use for it.
Browsable at Admin -> Audit Log (most recent 200 rows, newest first) --
nothing in the UI can edit or delete a row, by design.

**Login page picks a username from a dropdown, not a free-text field**
(2026-10-22, "trying to avoid people forgetting their username"):
`blueprints/auth.py`'s `_active_usernames()` lists every active account
(deactivated ones are left out -- they can't log in regardless of what's
picked), sorted the same as `db.list_users()`. A failed attempt re-renders
the same dropdown with whatever was picked still selected
(`selected_username`), rather than resetting to the placeholder. Signing in
successfully -- including the very first login's forced change-password
step, and visiting `/login` while already signed in -- now lands on
`/dashboard` (changed from the Rework log), confirmed live across all
three paths; an explicit `?next=` (e.g. bounced here by `role_required`)
still takes priority over that default.

**The login form auto-submits once a 4-digit PIN is typed** (2026-10-22,
"shouldn't need to click log in") -- `login.html`'s own inline script
submits the form the moment the PIN field matches `/^\d{4}$/`, as long as a
username is already picked (guards against auto-submitting with no
username selected, which would just bounce back with an error). Viewer
accounts with no PIN still click "Log in" themselves -- an empty field has
no unambiguous "finished typing" moment to trigger on.

**Admin page** (`/admin`, admin-only, `blueprints/admin.py` + `templates/admin.html`):
client-side tabs (`.tab-bar`/`.tab-btn`/`.tab-panel`, plain show/hide on click,
persisted via `location.hash` so a reload -- every action here does
`location.reload()` on success -- returns to the same tab instead of always
snapping back to the first one) over SQL/ERP Connection (test connection,
trigger `erp_sync.sync_items`/`sync_colours`, shows last-synced counts, plus
the Test data toggle -- see "Test data" below), Reasons (create +
activate/deactivate + inline edit -- 2026-10-22, `services.admin_data.
save_reason` identifies the row by `id` so renaming the reason text itself
is safe, and cascades the new wording into every historical `rework_events`/
`turret_events` row that used the old one, same non-FK "rename everywhere"
convention as Work Centres below), Door Codes (merged with the old
standalone Door Types tab 2026-10-20 -- see "Sales Order lookup" below),
Work Centres (create + activate/deactivate + inline edit -- Name and Sort
order together under one Edit/Save/Cancel, same pattern as Reasons; the
separate Rename-button/`prompt()` flow this started as was folded in
2026-10-22, replaced by `admin_data.save_named`, one combined save instead
of two separate calls -- nothing is ever hard-deleted, since historical
`rework_events` rows reference these by plain text, not a foreign key, and
must keep displaying correctly even after one's retired; `sort_order` is a
plain integer admin can set per row, already the column `reference_data.
list_work_centres`/`admin_data.list_named_all` both `ORDER BY` for the
entry form's dropdown and this table, so setting it here takes effect in
both places with no further wiring), Colours (read-only + local activate/deactivate, since the list
itself is ERP-owned), Items (`rule` is the only editable field -- everything
else is ERP-owned), and Users (full port of Scheduler's Users tab, in its own
`blueprints/users.py`/`/api/users/*`, same split as Scheduler). Most actions
just `location.reload()` on success rather than patching the DOM --
deliberate, this page is used occasionally, not continuously, so the simpler
approach wins over a hand-rolled SPA.

**Historical import & ongoing Excel import** (`services/rework_import.py`,
`import_rework_log.py`, Admin -> Import from Excel): the real workbook's
`REWORK` sheet (12,343 rows back to Jan 2023) is fully imported --
11,961 landed, 199 skipped for a genuinely missing required field (~1.6%,
typical of a hand-maintained sheet), one-off duplicates within the sheet
itself collapsed. Historical rows keep the *spreadsheet's own* cost figures
(columns L/M/N, cached formula results) rather than recomputing from today's
item costs, which would silently rewrite history every time a cost changes --
contrast `services.rework.create_event`, which *does* recompute, for new
entries. Dedup is a SHA-256 of each row's raw cell values
(`rework_events.source_row_hash`, nullable+unique -- NULL for normal web-form
entries never collides), so re-uploading the same workbook, or a newer export
of it, via Admin -> Import from Excel is always safe: already-imported rows
are silently skipped, confirmed live (re-uploading the full workbook a second
time reported 0 inserted, 12,019 already-imported, with the live row count
unchanged). **Important implementation note**: don't trust `cur.rowcount`
after `INSERT ... ON CONFLICT DO NOTHING` against this project's dev database
(PGlite) -- it reports a row as inserted even on a no-op conflict. Use
`RETURNING id` and check whether `cur.fetchone()` returned a row instead; this
cost real debugging time once already (see git history) and would silently
have shown "12,019 inserted" on every re-upload forever otherwise. The old
spreadsheet's NAME column (who logged it) has no real user account behind
it, so it lands in `entered_by_name` (free text), separate from
`entered_by_user_id` (a real FK, only ever set by the web form going forward).

**Dashboard** (`/dashboard`, any logged-in role, `blueprints/dashboard.py` +
`services/reporting.py`): replaces the spreadsheet's pivot sheets -- entries/cost
per week, top reasons, door-type and colour breakdowns, over a selectable
period (30/90/180/365 days). "Total cost" sums material + labour where
present, so historical rows' real labour costs still count even though
nothing computes new ones (see "Labour cost is on hold" above). Charts are
hand-built SVG (`static/charts.js`, loaded via the `dataviz` skill's
procedure) rather than a charting library -- no new runtime dependency, full
control over the one-axis-per-chart / categorical-palette / hover-tooltip
rules that skill requires. A measure needing two different scales (e.g. count
vs. cost) is always two separate single-axis charts, never a dual-axis one.

**Sales Order lookup** (`services/erp_lookup.py`, `GET /api/orders/<so_number>`,
wired into `templates/rework_new.html`'s SO Number field via blur/Enter):
pre-fills the entry form from the actual order instead of typing from memory.

Reads from a local Postgres cache (`synced_orders` / `synced_order_materials`,
migration `0007`), refreshed once a day by `services.erp_sync.sync_orders`
(its own schedule in `services/scheduled_sync.py`, defaults to daily +
enabled -- separate from the weekly items/colours schedule since the entry
form depends directly on this one being fresh) or on demand via Admin's
"Sync Orders Now". **This used to query SyteLine live on every single
lookup** -- changed 2026-10-21 after real use showed the obvious problem:
every operator typing an SO number was its own live ERP round trip, slow
even when SyteLine was up and a hard failure whenever it wasn't (which
happened repeatedly during this app's own development). A brand-new SO
created minutes ago won't resolve until the next sync -- a deliberate
trade-off, not a bug; the manual "Sync Orders Now" button exists for when
someone needs it sooner.

- `coitem_all` (`queries.ORDERS_SYNC_QUERY`, no filter -- this table only
  ever holds lines that haven't shipped yet, so there's nothing to window)
  -> Job Number, Height, Width, a Colour suggestion (In/Out codes resolved to
  names via the already-synced `colours` table by `code`), and a Door Type
  suggestion via `cpq_door_codes` (below). `coitem_mst_all` (shipped/
  completed lines) isn't synced yet -- would extend coverage to orders a
  rework gets logged against after they've shipped; see `queries.py`'s
  comment on `ORDERS_SYNC_QUERY` for exactly what's confirmed vs. still
  needs checking live before adding it.
- `jobmatl_mst` (`queries.job_materials_for_jobs_query`, scoped to just the
  job numbers the orders sync found, not the whole table) -> each job's real
  material lines, which replace the Product Code field's free-text
  item-master search with just that job's own materials
  (`productCombo.refresh(...)`; typing while scoped filters locally, no
  further server calls -- cleared by clearing the SO number). **Caught a
  real gotcha here**: `jobmatl_mst.cost` is a PER-UNIT figure (confirmed
  equal to `item_mst.unit_cost` on every sampled row), not the line's
  extended total -- summing it directly across a job gives a meaningless
  number (summed unit prices, not a cost); the real total is
  `SUM(matl_qty * cost)`. Confirmed on a real job: $464.52 extended vs. a
  wrong $309.67 from naively summing `cost` alone.
- When Type is "Scrap Entire Door", that extended sum across every material
  on the job becomes the material cost (`services/costing.compute_costs`'s
  `full_door_material_cost` param) -- the real cost of everything that went
  into the door, not an estimate from one part's standard cost. Same
  never-trust-the-client rule as everywhere else: the client sends only
  `so_number`; `services.rework.create_event` re-runs the cached-order
  lookup itself and ignores any cost figure the client might have attached
  preview-side.
- `sync_orders` never deletes/deactivates a cached order or its materials --
  a row dropping out of `coitem_all` just means that order shipped, and a
  rework entry might still legitimately reference it after that. Every sync
  only adds/refreshes; nothing already cached is removed.

**`cpq_door_codes` table is Door Types** (Admin -> Door Codes, migrations
`0004`-`0006`, merged with the old standalone Door Types tab 2026-10-20):
`cpq_code` (from `coitem_all.Uf_aplCPQDoorProdCode`, e.g. `AXL`) paired with
two admin-typed free-text fields, neither validated against anything --

- `family_name` **is** this app's Door Type list. `services.reference_data.
  list_door_types()` reads `DISTINCT family_name` straight off this table --
  there's no separate door_types table backing the entry form's Door Type
  dropdown anymore (the old `door_types` table is left in the schema, unused,
  rather than dropped -- nothing references it by foreign key, so there's no
  integrity reason to remove it). A code's `family_name` also feeds the SO
  lookup's Door Type suggestion (`get_door_type_for_cpq_code`); if it doesn't
  match the operator's intended type, Door Type is just left for them to set
  manually, same as an unmapped code -- never a hard error either way.
- `description` is optional extra detail beyond the family name, with no
  other role in the app.

Originally this was a single `door_type` column validated against a dropdown
of existing `door_types.name` values -- removed the same day after real use
showed why that was wrong: several codes needed a value before the matching
type existed yet (e.g. `AXL` = "Axis Lite", confirmed with the department as
a distinct variant, not plain Axis -- a first guess that mapped every suffix
to its base type was wrong), so requiring the dropdown's value to already
exist was a chicken-and-egg problem, not a safety net.

The Admin tab renders rows **read-only by default with a per-row Edit
button** (reversed 2026-10-22 from the original "every row is a live input"
design -- same `.view-val`/`.edit-val` pair per cell, toggled by an
`editing` class on the row, as the Reasons tab -- see static/style.css).
Clicking Edit reveals the code/family name/description inputs plus
Save/Cancel (Cancel reverts to the row's last-saved values rather than
discarding it, unless the row was never saved at all, in which case it's
just removed). The Delete button was replaced with the same deactivate/
reactivate pattern as Reasons/Colours/Work Centres (requested 2026-10-22,
migration `0013` adds `cpq_door_codes.active`) -- a deactivated code drops
out of `reference_data.list_door_types()` and `get_door_type_for_cpq_code`
(treated the same as an unmapped code: the SO lookup just leaves Door Type
for the operator to set manually) without touching historical
`rework_events` rows that already used its family name. `save_cpq_door_code`
carries the old row's `active` flag across a rename (reading it before the
delete-and-reinsert a code rename does) so renaming a deactivated code
doesn't silently reactivate it. A "Check SyteLine for new codes" button
(`erp_lookup.list_unmapped_cpq_codes`,
a live ~17s ERP query since there's no index on that column -- deliberately
on-demand, not run on every Admin page load, see "Performance" above)
appends blank rows for any code found that isn't already listed -- a
brand-new row has nothing to show read-only yet, so it's added already in
edit mode. Editing a row's code (not just its other fields) acts like a
rename: `services.admin_data.save_cpq_door_code` deletes the old `cpq_code`
row first since it's the primary key, rather than leaving both behind.

## Where to look for changes

- Cost-calculation rule change -> `services/costing.py` (pure functions, unit
  tested in `tests/test_costing.py` -- no DB needed to test this file).
- A dropdown's options change -> Admin page (Reasons/Door Types/Work Centres
  tabs), not code -- colours come from the ERP sync instead.
- Entry-form layout/fields -> `templates/rework_new.html` + its inline script;
  mirrors the UI mockup design reviewed before build (severity-coded Type
  control, searchable Reason/Colour comboboxes, live ERP-backed Product Code
  lookup, sticky cost-preview panel / mobile bottom bar).
- New Dashboard chart -> add a query to `services/reporting.py` + a
  `RWCharts.barChart`/`lineChart` call in `templates/dashboard.html`'s inline
  script (see `static/charts.js`).
- ERP reconciliation (`erp_scrap_transactions` table exists; sync + comparison
  view not yet built) and the Turret scrap log (`turret_events` table exists;
  no UI yet) are both scoped but not implemented.

## Not yet done

- **ERP reconciliation** (see "Where to look for changes" above). The
  Turret workbook's own `Pivot` tab is a hand-kept version of exactly this
  for turret sheet-stock scrap (see "Turret log" below) -- a natural
  starting point once this gets built, not wired up yet.
- **The *old combined* workbook's own 2025 Turret history**: `2023-2026
  Rework Data.xlsx` has its own `Turret` tab covering all of 2025 (5,735
  rows) -- a different source file from the standalone `Turret Sheet Audit
  2024/2025/2026.xlsx` workbooks (all three of which **are** imported, see
  "Turret log" below) -- still not imported, no current plan to.

## Turret log (`/turret`, any logged-in role, `blueprints/turret.py` +
`services/turret.py` + `templates/turret_list.html`)

Log of the turret machine's raw sheet stock -- separate from
`rework_events` (which tracks finished-door rework/scrap, not raw
material). Two sources of rows now: the historical import (scrap-only, see
below) and the entry form (2026-10-21, see "Turret entry form" below),
which can log a job with no scrap at all.

**Historical import is still scrap-only**: Sheet1 of each source workbook is
really a job-sheet-usage tracker that *also* has scrap recorded against some
rows, not a scrap log on its own -- most rows have no scrap at all, just
which sheets a job used. The importer only ever cares about the scrap side
(2026-10-21 decision), so it drops every row with nothing scrapped. This
restriction is specific to `services/turret_import.py` -- it has nothing to
do with what the entry form is allowed to save.

A row can have scrap recorded against more than one of its 3 sheet slots
(A/B/C), each with its own date/sheet/qty -- a blank slot just means that
slot had nothing scrapped, not missing data.

**Import** (`services/turret_import.py`, `import_turret_log.py`): same
dedup convention as `services/rework_import.py` (`source_row_hash`, safe to
re-run against a newer export). All three standalone `Turret Sheet Audit
YYYY.xlsx` workbooks -> `Sheet1` are imported (1,305 scrap rows total,
spanning Jan 2024 - Dec 2026):

- **2026** (confirmed live 2026-10-21): 382 inserted, 5,333 skipped for no
  scrap recorded, 24 skipped for a genuinely missing date.
- **2025** (confirmed live 2026-10-22, identical column layout to 2026): 327
  inserted, 5,408 skipped for no scrap, 11 skipped for a missing date.
- **2024** (confirmed live 2026-10-22): a genuinely **older column layout**
  -- no Week column at all, and only one shared "Scrap Date" for the whole
  row instead of an independent date per sheet slot (confirmed against real
  scrap rows before trusting it, e.g. a guillotine-cut-wrong row with scrap
  on both slot A and B lined up exactly). `services.turret_import.
  COL_2024`/`_clean_2024` handle this: `week_num` is derived from
  `event_date`'s own ISO week (there's nothing else to use), and the single
  shared Scrap Date is applied to every slot that actually has scrap on
  that row. `import_turret_log.py` takes an optional `2024` argument to
  select this layout (`python import_turret_log.py "Turret Sheet Audit
  2024.xlsx" 2024`) -- 596 inserted, 5,246 skipped for no scrap, 2 skipped
  invalid (1 missing date, 1 with a literal `29` typed into the Scrap Date
  cell instead of a date -- a genuine source data error, caught by the
  per-row savepoint and skipped rather than guessed at).

A missing job number doesn't exclude a row -- a meaningful share of rows
across all three years have a literal `Sales #` of "REWORKS" (or similar
free text like "DEC REWORK") with no real job number (turret sheet stock
consumed for door reworks rather than a numbered production job) -- those
import fine with a NULL job_number.

**Two tabs** (`.tab-bar`, same client-side pattern as the Admin page):

- **Scrap log**: the raw per-job view above, with Month/Year/Type/Job
  number filters.
- **Scrap write-off** (`services.turret.scrap_summary_by_week`): scrap
  grouped by write-off week and item, un-pivoting all 3 sheet slots into one
  series first so a job scrapping two different sheets isn't silently
  dropped to one line. The write-off week is *derived* from each slot's own
  `scrap_date` (one ISO week later, always a Monday) -- **not** the sheet's
  own pre-typed `scrap_week`/`scrap_year` columns, despite those existing
  for exactly this purpose. Got this wrong the first time (trusted
  `scrap_week` directly, matching what the sheet seemed to be for): confirmed
  live 2026-10-21 that trusting it gave only a 9.8% exact-match rate against
  real ERP data, while deriving from `scrap_date` the same way
  `services.rework` derives from `entered_date` (not `rework_date`) gave
  93.5%. Same underlying lesson both places: a human-typed "intended" week
  drifts from reality; the date something was actually recorded on is the
  more reliable signal. `week_num` (the job's own *production* week, not
  when the scrap was recorded) is still shown as "Production week(s)" for
  context (renamed from "From week(s)" 2026-10-22 for clarity -- this app
  has several different "week" concepts, so the column is explicit about
  which one it is), unrelated to the write-off-week calculation. More than
  one can legitimately appear in a single row: several different jobs
  (each with their own production week) can all have scrap that's due for
  write-off in the same later week, so this column is showing every
  distinct production week that contributed -- not a bug, and not expected
  to always be singular. Item descriptions join
  against the already-synced `items` table -- raw sheet stock (e.g.
  `5902412`) is classified under `uf_emdaProductGroup = 'DO'` same as
  finished door parts, confirmed present there already, so no extra sync
  was needed for this.

  **"Production week(s)" showed the literal text "None"** (confirmed live
  2026-10-22): every row saved through the new Turret entry form
  (2026-10-21 onward) left `week_num` NULL -- `create_event`'s INSERT simply
  never included it, unlike the historical importer, which always carries
  the old spreadsheet's own hand-typed week. `array_agg(DISTINCT week_num
  ...)` then had a literal `None` mixed in alongside real week numbers from
  historical rows aggregated into the same write-off-week/item group, and
  Jinja's `join` filter stringified it. Fixed at the source: `create_event`
  now stamps `week_num` from `event_date`'s own ISO week (same `EXTRACT(WEEK
  FROM ...)` definition used everywhere else in this app), set once at
  creation like `scrap_date`, never touched by `update_event`. Migration
  `0012` backfills every row already saved before this fix. The query also
  now filters NULLs out of the `array_agg` defensively (`FILTER (WHERE
  week_num IS NOT NULL)`), and the template falls back to "—" if
  `from_weeks` ever comes back empty, so this can't resurface even in some
  future edge case.

  **The whole Turret page was 500ing** (confirmed live 2026-10-22): a row
  with a `scrap_qty` set but a NULL `scrap_date` (a real historical data
  gap -- the importer only carries whatever the sheet actually had, see
  `services/turret_import.py`) made `_WRITEOFF_DATE_EXPR` compute a NULL
  write-off date, which `list_available_scrap_weeks()` then returned as a
  `{write_off_year: None, write_off_week: None}` row; `blueprints/turret.py`
  passing that straight into `int(write_off_week)` crashed with
  `ValueError: invalid literal for int() with base 10: 'None'` (the
  stringified `None`, not a real NULL, by the time it got there) on every
  single page load, for every user. Fixed at the source: `_UNPIVOT_SCRAP`
  now requires `scrap_date_x IS NOT NULL` alongside the existing
  `scrap_qty_x IS NOT NULL` check on all three slots, so a scrap qty with no
  recorded date simply doesn't surface in either the write-off summary or
  the available-weeks list -- same "can't write off what has no write-off
  date" logic as everywhere else on this tab, not a new exception to carve
  out.

  **ERP reconciliation is wired up** (2026-10-21): the department provided
  the real Power Query source behind their own write-off pivots, confirmed
  live against `alpac_App` before trusting it (1,211 rows for 2025-2026,
  Doors only). See "ERP scrap reconciliation" below for the full detail --
  the "ERP actual" column now shows a green "matches" badge, a red mismatch
  with both numbers, or grey "Not in ERP yet" when nothing's synced for
  that item/week.

## Turret entry form (`/turret/new`, `/turret/<id>/edit`, `operator`+,
`blueprints/turret.py` + `templates/turret_new.html`)

Two-stage, matching how the real process actually works (confirmed with the
department 2026-10-21): `create_event` saves a job's material usage
(`event_date`, SO number, job number, door type, colour, up to 3 Sheet
material slots with qty each); most turret jobs never need anything past
this. `update_event` reopens that same row -- any API client, in practice
the same form at `/turret/<id>/edit` -- to add rework/scrap later: a
rework type (`Replacement Parts` / `Rework Entire Door`), a reason, and up
to 3 rework material slots, each getting its own `scrap_date` stamped
server-side.

**Reason reuses Doors' shared `rework_reasons` list** -- originally built
as its own separate `turret_reasons` table/Admin tab (2026-10-21), reversed
the next day (2026-10-22): the department asked for the shared list
instead. `turret_reasons` is dropped (migration 0011; it never held any
real data, nothing to migrate). `turret_events.reason` is unaffected --
still a plain text column, no FK either way, just drawing its values from
`rework_reasons.reason` now via `reference_data.list_reasons()` instead of
a Turret-only source.

**SO number auto-fill** (2026-10-22): entering an SO number looks up
`/api/orders/<so>` -- the exact same endpoint and local `synced_orders`
cache the Doors form already reads (`services/erp_lookup.py`), never
SyteLine live -- and fills in Job Number, Colour, and Door Type. Door Type
is a special case: Turret's own list is just whatever's already in
`turret_events`, not a curated list, so if a looked-up order's door type
isn't in there yet, the form adds it as a new option on the fly instead of
silently failing to select anything.

**Material 1/2 (and Rework material 1/2) scope to the job's real BOM**
(2026-10-22) -- the lookup's `materials` array (every line on the job from
`jobmatl_mst`, the same data Doors' Product Code scoping uses) is filtered
down to whichever lines are Sheet items, and that becomes the option list
for those 4 selects, confirmed live against a real job (22 total material
lines, 1 Sheet match). **Slot 3 ("Other") is deliberately never touched** --
it always offers the complete Sheet list, for whatever isn't on the planned
BOM. If a job's BOM has no Sheet matches at all, Material 1/2 fall back to
the complete list too rather than being left with nothing selectable.
Rebuilding a `<select>`'s options wipes its current value, so
`populateSheetSelect` always re-adds whatever was already selected (even if
it's since fallen outside the newly-scoped list) rather than silently
clearing it.

**Sheet classification now comes from `items.plan_code = 'SHT'`, a real ERP
field** (2026-10-22) -- replaces the hand-curated list this started as. The
original 5-code list came from the department's own scrap-transaction query,
which only ever classified codes it had actually seen scrapped historically
-- it wasn't meant as "every sheet size Turret can load", and it bit
immediately: a real job (S000564896) needed `5902412.0.9` (a 0.9mm variant
of `5902412`), which silently wasn't in the set.

`plan_code` (synced via `ITEMS_QUERY` into `items.plan_code`, migration
0010) is a genuine SyteLine classification, confirmed live with zero false
positives against everything tested: all 5 originally-known codes have
`plan_code = 'SHT'`, plus 4 more real sheet sizes found the same way
(`24123`, `36121.5`, `3902210.0.9`, `5902410`) -- 9 total. Confirmed
`plan_code` cleanly excludes what a naive `description ILIKE '%SHEET%'`
search could not: ANO/PC/pretreat surcharge line items with "SHEET" in
their name (`plan_code = NULL`), poly backing sheet (`plan_code = NULL`),
and a finished door-frame part whose description just happens to mention
"sheet" (`00346.500.01`, `plan_code = 'EXT'`, not `'SHT'`).

`services.reference_data.list_sheet_items()` (Turret's Material/Rework
dropdowns) and `services.erp_reconciliation.sheet_item_codes()` (the Doors
write-off exclusion) both now query `items.plan_code = 'SHT'` directly --
no hardcoded list anywhere, no cache to invalidate; a future items sync
that changes which items have `plan_code = 'SHT'` takes effect everywhere
automatically. `queries.SCRAP_TRANSACTIONS_QUERY`'s own `Sheet`/`Plank` CASE
WHEN is left exactly as the department wrote it (not switched to
`plan_code`) since it's a verbatim department report feeding a
reference-only column, not actual matching logic -- the two are allowed to
diverge, and now do (the `plan_code`-based set is broader).

**`3902210.1.2`'s missing `plan_code` -- resolved on the ERP side**
(2026-10-22): the 2.2m×1m×1.2mm sheet (confirmed needed on a real job
alongside `3902210.0.9`) had no `plan_code` set in SyteLine at all; the
department set it to `SHT` directly in SyteLine, confirmed live
(`erp.fetch_all` against `item_mst`) and synced in via Admin -> Sync Items
-- 10 Sheet items now resolve automatically instead of 9, with no app-side
change needed since Turret's material dropdowns and Doors' write-off
exclusion both already derive from the same `items.plan_code = 'SHT'`
query. Also still true: the bare code `3902210` (one of the original 5)
doesn't exist in the synced `items` table at all -- `3902210.0.9`/
`3902210.1.2` do -- so it was never actually reachable through the old
hand-curated list either.

**All 6 material slots (3 "good" + 3 rework) are constrained to Sheet
items only** -- confirmed explicitly: "Turret only deals with sheet." The
picker is a plain `<select>` (not a search combo like Doors' Product Code)
since `erp_reconciliation.SHEET_ITEMS` is a fixed list of 5 codes --
`services.reference_data.list_sheet_items()` joins that set against the
already-synced `items` table for descriptions.

**`scrap_date` is stamped once, not on every save**: `update_event` checks
the row's *existing* `scrap_date_a/b/c` before writing -- if a slot already
has one, it's preserved untouched; only a slot getting rework data for the
*first* time gets stamped to today. Confirmed live: re-saving an entry that
already has rework recorded, even changing unrelated fields, doesn't move
its scrap_date forward. This matters because the Scrap write-off tab's ERP
reconciliation depends on that date being when the rework was *actually
recorded*, not whenever the row happened to be touched again -- same
principle as `entered_date` driving Doors' write-off week (see "Scrap
write-off (Doors)" above).

**Scrap cost** (2026-10-22, `services.costing.compute_sheet_scrap_cost` +
`services.turret.update_event`): `turret_events.scrap_cost` (the same single
column historical imported rows already carried from the old spreadsheet,
previously never written by the web form at all) is now recomputed on every
`update_event` save -- qty x each scrap slot's item `std_cost`
(`services.reference_data.get_item`), summed across however many of the 3
rework material slots have scrap recorded this time. No `rule` multiplier
involved (that's Doors' units-per-part concept for a cut part; Turret scraps
the raw sheet itself). Same never-trust-the-client rule as every other cost
figure in this app: the entry form shows a live client-side estimate as the
operator picks a rework material/qty (`list_sheet_items()` now also returns
`std_cost` for exactly this), but the server always recomputes and stores
its own figure on save, ignoring whatever the client displayed. Confirmed
live: 3 x `5902412` ($166.96) + 1 x `79020062` ($97.29) = `$598.17`, matching
both the entry form's summary panel and the Scrap log table's new "Scrap
cost" column exactly. Historical imported rows keep their own spreadsheet
figure untouched, same pattern as Doors' historical cost preservation (see
"Historical import" above) -- only a save through `update_event` ever
recomputes this column.

**Schema** (migration 0009): `turret_events.type` renamed to `door_type` --
it already held door-family values ("Plasma", "Classic", ...) for every
imported row, i.e. it already meant Door type, not a type split. The
replace-vs-rework-whole-door distinction is genuinely new (`rework_type`),
since the imported sheet never carried one. `colour` and `reason` are also
new -- `reason` is free text (same non-FK convention as
`rework_events.reason`), populated from `rework_reasons.reason` (Doors'
shared list, see "Reason reuses Doors' shared `rework_reasons` list" above)
going forward; `scrap_code` (the imported sheet's own "CODE - DESCRIPTION"
format) is untouched and stays import-only.

The `.view-val`/`.edit-val`/`editing`-class CSS pattern (`static/style.css`)
built for the now-dropped Turret Reasons tab (read-only rows + a per-row
Edit button, instead of every field being a live input) is kept -- Door
Codes is moving to this same pattern next (see TODO.md), so it's not dead
code even though nothing currently uses it.

**Scrap write-off (Doors)** (`services.rework.scrap_writeoff_summary`, a
second tab on `/rework` next to the Rework log, same `.tab-bar` pattern as
Turret and Admin): same idea as Turret's write-off tab, different source
and a different week rule. `rework_events` has no pre-entered write-off
week (Turret's sheet has one written by hand) -- so it's *derived*: one ISO
week after whatever week `entered_date` falls in (`write_off_date =
date_trunc('week', entered_date) + 7 days`, always a Monday) -- **not**
`rework_date` (when the defect happened). Got this wrong the first time
(used `rework_date`) and it mattered: confirmed live 2026-10-21 with three
rows that all shared the same `rework_date` but had different
`entered_date`s (one entered promptly, two entered ~2 weeks later) -- only
the promptly-entered one had actually been written off in the week my
`rework_date`-based version predicted; the other two didn't show up in ERP
until the week after *their own* entered_date. Switching to `entered_date`
took the exact-match rate across all of history from 24% to 66%, including
every single row in two full weeks checked by hand against the department's
own numbers. Confirmed this is exactly how the real process works: the
weekly write-off batch runs off whatever's been entered into the tracker
that week, not off when the defect physically occurred -- the department's
own spreadsheet uses entered_date for this too.

Only `type = 'Replace Part'` rows with a non-NULL `qty_to_remove` appear
here (2026-10-21: Rework/Recoat is never written off in SyteLine at all,
confirmed with the department, so including it overstated "ready for
write-off"). Scrap Entire Door rows use product_code `"DOOR"`, which isn't
a real item, so they fall out of `qty_to_remove IS NOT NULL` naturally too.
Sheet items (`erp_reconciliation.SHEET_ITEMS`) are excluded -- they're
Turret's raw sheet-stock, already reconciled on that tab, so including them
here would double-count across both tabs. **Plank items (e.g.
`00392.215.01`) deliberately stay in** -- confirmed with the department
these belong in the Doors view, unlike Sheet, even though Plank's own
reconciliation is messier in practice (see "ERP scrap reconciliation"
below) -- that's a real property of how Plank gets consumed, not a reason
to hide it.

Grouped by (write-off year, write-off week, product_code) -- ISO week
numbers repeat every year, so the year is always paired with the week
(`ISOYEAR`, not plain `YEAR`) to avoid merging e.g. week 1 of 2025 with week
1 of 2026. Defaults to the most recent week with data on first load (an
unfiltered view across 2023-2026 is thousands of rows, not a useful landing
view) -- "All weeks" is still one click away.

## ERP scrap reconciliation

Both Scrap write-off tabs' "ERP actual" column is real (2026-10-21) -- the
department supplied the exact Power Query source behind their own write-off
pivots, confirmed live against `alpac_App` before being trusted for
anything (1,211 rows for 2025-2026, Doors only -- same rule as every other
ERP query in this app).

**Source** (`queries.SCRAP_TRANSACTIONS_QUERY`, `services.erp_sync.
sync_scrap_transactions`, `erp_scrap_transactions` table, wholesale-replaced
every sync per its migration-0001 comment -- a transaction feed, not
reference data with a stable key to upsert against): `matltran_mst`
(SyteLine's job *material transaction* history) filtered to
`reason_code = 'SCR'` -- confirmed this is specifically what marks a scrap
write-off among 44 distinct reason codes on that table (7,483 'SCR' rows
plant-wide). Joined to `item_mst` for description/product_group, filtered
to Doors (`uf_emdaProductGroup = 'DO'`), pulling the last 2 calendar years.

Three things confirmed live that would otherwise have silently broken
reconciliation:
- **`qty` is signed, and overwhelmingly negative** (1,193 of 1,211 real
  rows) -- SyteLine records a scrap write-off as stock *leaving* inventory,
  not a positive "amount scrapped" count the way this app's own
  qty_to_remove/scrap_qty fields are. `services.erp_reconciliation` sums
  the signed qty per (item, ISO year, ISO week) and takes `abs()` of the
  total -- summing first (rather than summing absolute values) also makes a
  correcting reversal (a wrong entry immediately offset by its exact
  negative) net out to zero automatically, which is correct, not a bug to
  special-case.
- **`item_mst.product_code` is a family/category code** (e.g. "PLD", "CSD",
  "DR"), confirmed **not** the same thing as this app's own `product_code`
  columns (which store the real item/part number everywhere else --
  rework_events.product_code, turret_events.sheet_a). Reconciliation always
  matches on `item`, never on this field -- it's kept in the synced table
  only for reference, same shape as the department's export.
- **A whole scrapped door shows up as item `"Door"`** ("Configurable Door",
  product_code "DR", and the only row with a non-zero `scrap_labour_cost`
  found) -- the ERP-side equivalent of this app's own "Scrap Entire Door"
  (product_code `"DOOR"`). Not matched against anything yet (Doors
  write-off only covers Replace Part/Rework-Recoat, see above) -- noted
  here since the item text differs by case and isn't an exact string match
  if this gets wired up later.

The department's own query also carries a hand-curated `Sheet`/`Plank`/NULL
item classification (`Sheet` = the same 5 raw sheet-stock codes already
known from the Turret tracker; `Plank` = 2 codes, `00392.260.01`/
`00392.215.01`) -- kept as-synced for reference. `erp_reconciliation.
SHEET_ITEMS` mirrors the Sheet half so Doors' write-off tab can exclude them
(Turret already reconciles them). Plank is a genuinely messier case,
confirmed live 2026-10-21 on `00392.215.01`: it has only 63 real `SCR`
transactions in two years (summing to ~1,977 units) against **16,539**
regular (no-reason-code) consumption transactions summing to +11,540 --
i.e. it's a bulk/continuous production material, not something scrapped
one logged defect at a time, and most Plank "Replace Part" entries in this
app likely never produce a dedicated SyteLine scrap transaction at all
(the material probably just gets reissued from regular stock instead). The
department still wants Plank visible on this tab regardless -- it just
means a Plank mismatch isn't automatically a sign of a problem the way a
finished-part mismatch is.

**Matching** (`services.erp_reconciliation.erp_actuals_by_item_week`,
shared by both tabs): keyed by `(item, ISO year, ISO week)` derived from
`txn_date` the same way Turret/Doors derive their own write-off weeks (not
SyteLine's own non-ISO `DATEPART(WEEK, ...)`, which isn't even fetched).
Turret's own `scrap_year` column is entirely blank in the real sheet, so
its ISO year is derived from whichever scrap-slot date is present instead
of trusted from the sheet.

**Admin** (SQL Connection tab): a third stat row + a "Sync Scrap
Transactions" button, same pattern as items/colours/orders. **Scheduled
Tasks**: a third schedule, defaulting to weekly on Monday (matches "scrap
every Monday for last week" so a Monday sync naturally picks up the week
just finished).

The same workbook has two other tabs that matter but aren't wired up:
- **`Pivot` tab**: a hand-kept weekly scrap write-off log (item code, summed
  scrap qty, week number, write-off date, who processed it) with the note
  "Scrap every Monday for last week" -- i.e. this is literally the record of
  what's been entered into SyteLine as turret scrap, done by hand. This is
  the natural seed for the ERP reconciliation TODO above, once that's
  scoped -- not read or imported anywhere yet (2026-10-21: asked the
  department what this should become; read-only display vs. a real
  SyteLine-comparison feature is still an open decision).
- **`Transformed Data` tab**: just an Excel-generated byproduct from the
  first time someone built a PivotTable off this workbook (a small Jan-Feb
  2024 slice) -- not a real historical archive, deliberately ignored.

## Test data (Admin -> SQL Connection -> "Test data")

A fake Sales Order (`services/test_data.py`) for safely exercising the Doors
and Turret entry forms end-to-end -- new entry, reopen/edit, Scrap
write-off -- without risking a real order number (requested 2026-10-22:
"make a fake sales order... don't use a real one"). Toggled on/off, not a
one-off script, so it's a repeatable sandbox rather than a second permanent
data set to maintain.

SO `test` (lowercase, exactly -- so_number matching is case-sensitive, same
as every other SO number in this app), Job `J009999999`. Only the SO/job
linking is fake -- everything it points at is real: colour `ARCTIC WHITE
MATT 20S1358M` (code `AW`, an existing row -- "Test" isn't a real colour,
confirmed with the department 2026-10-22 after an earlier version of this
invented a fake one), door type `Plasma` (resolves via the real,
already-mapped `cpq_door_codes` row `PLS` -- no fake code mapping needed).
BOM is 4 real item lines under the fake job (`synced_order_materials`): 2
Sheet items (`5902412`, `79020062`, for Turret's Material 1/2 BOM-scoping) +
2 real Plasma door parts with a `rule` set (`00347.500.01`, `00349.500.01`,
for Doors' Replace Part costing) -- confirmed live the SO lookup, both
forms' auto-fill, and Scrap Entire Door's full-door-material-cost calc
(`801.64` = `SUM(qty * unit_cost)` across all 4 lines) all work off this
exactly like a real order.

Enabling just seeds the fake order/materials -- nothing in
`rework_events`/`turret_events` is pre-created; you log real entries against
it yourself through the real forms to test create/reopen/edit and see them
show up on both Scrap write-off tabs normally (write-off derivation doesn't
care whether the SO is real).

**Test-flagged rows are admin-only** (2026-10-22, after a real operator ran
into test rows mixed into their own log): `blueprints/rework.py` and
`blueprints/turret.py`'s `list_page()` both filter out any event or
write-off row tied to the fake SO (`so_number`/`sales_number`, or
`includes_test_data`) before rendering, unless `current_user()["role"] ==
"admin"`. Confirmed live with a real operator account: zero test rows shown
to it while the same data still shows to admin. This only touches the two
log/write-off list views -- the entry forms' pink TEST banner and the `test`
SO's own auto-fill are unchanged for operators, since operator is exactly
who needs to be able to log an entry against it in the first place.

**The TEST ORDER banner never actually hid, on any page load, for anyone**
(confirmed live 2026-10-22, reported as "test data is enabled" when the
Admin toggle was actually already off -- the real bug was purely visual, on
the entry form itself; a real CSS gotcha, not the entry-form JS). The
banner is toggled via the element's native `hidden` property
(`testOrderBanner.hidden = ...`), but `.conn-banner{display:flex; ...}` is
an **author stylesheet** rule -- author rules always beat the browser's
built-in `[hidden]{display:none}` default regardless of selector
specificity, since UA-origin styles sit below author styles in the CSS
cascade no matter how it's written. So setting `.hidden = true` correctly
set the HTML attribute, but it had zero visual effect: the banner rendered
every time, with every so_number, fresh page load or not. My first attempt
at this (calling `updateTestBanner()` after the "Clear form" button's
`form.reset()`, since `reset()` doesn't fire `input` events) was a real gap
too, but not the actual bug being reported -- it couldn't have been, since
the banner never hid even on a correctly-computed `hidden = true` to begin
with. Fixed at the actual source: `static/style.css` already has the exact
same fix for this exact class of bug on `.combo-list` (`.combo-list[hidden]
{display:none !important;}`) -- added the matching `.conn-banner[hidden]
{display:none !important;}` rule, which actually wins the cascade. The
`updateTestBanner()`-after-`reset()` call stays in both forms regardless --
still correct given `reset()`'s real behavior, just not what was broken.

**A test entry is never silently indistinguishable from a real one**
(confirmed live 2026-10-22, after an earlier version only coloured a fake
colour row in Admin -> Colours, which doesn't touch the entry forms at all
since no colour anywhere renders a swatch there): the same pink "TEST"
styling (`static/style.css`'s `.conn-banner.test` / `.test-order-row` /
`.test-badge`) now shows on all four places a test entry can appear --
- the entry form itself (a banner above the form, shown whenever the SO
  field holds `test`, live as you type, both Doors and Turret),
- the Rework/Turret log tables (row highlight + badge next to the SO/Sales #
  cell, whenever that row's own so_number/sales_number is `test`),
- both Scrap write-off tabs (row highlight + badge on the product
  code/item cell) -- these are aggregated rows (grouped by week + item), so
  there's no single so_number column left to check directly; `services.
  rework.scrap_writeoff_summary` and `services.turret.scrap_summary_by_week`
  both carry `so_number`/`sales_number` through their CTEs and add an
  `includes_test_data` flag (`BOOL_OR(LOWER(so_number) = LOWER('test'))`)
  so a write-off row gets flagged if *any* of its underlying rows came from
  the fake SO, even when mixed in with real ones that week.

**Disabling is a full reset, not a soft hide**: confirmed live 2026-10-22 --
it deletes the fake order/materials *and* any rework_events/turret_events
logged against the fake SO number while testing, so nothing fake lingers in
real history or the Dashboard afterward. `so_number`/`sales_number` are
plain text everywhere (no FK), so this is a clean delete-by-value, no
cascade needed. The colour is real and shared, so disabling never touches
`colours` at all.

## Scheduled Tasks (Admin -> Scheduled Tasks)

`services/scheduled_sync.py` runs three ERP syncs (items, colours, orders) on
their own fixed clock-time schedules -- a background thread
(`start_background_thread`, started once from `app.py`) wakes every 30
minutes and checks each one (`run_if_due` for items+colours, which share one
schedule; `run_orders_sync_if_due` for orders, separate). A schedule is
`{enabled, frequency: daily|weekly|monthly, time: "HH:MM", day_of_week: 0-6}`,
settings-table-backed (`erp_sync_*` / `orders_sync_*` keys). "Due" means the
most recent scheduled clock-time (today's HH:MM for daily; this week's
weekday+HH:MM for weekly) has passed since the last sync -- a real wall-clock
time, not a rolling "N hours since last sync" window, since that's what the
admin UI's time/day pickers actually promise. Monthly stays a simple ~30-day
rolling check (no day-of-month picker -- not asked for). Checked only every
30 minutes, so a scheduled time can run up to ~30 minutes late.

Defaults: items/colours weekly, Monday 02:00; orders daily, 02:00 -- the
entry form's SO lookup depends on the orders one directly (see "Sales Order
lookup" above), hence daily instead of weekly.

Admin's manual Sync buttons (SQL Connection tab) always work regardless of
these schedules, same as before.

~~Length-charting tables~~ -- resolved 2026-10-20: `emdaLengthCharts`/
`emdaLengths`/`emdaLengthChartKey` exist but are empty (0 rows) in the live
ERP, confirmed unused. `items.length_std` (from `item_mst.uf_emdaLength`,
already synced) is the only real length data available -- nothing further
to build here.
