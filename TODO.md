# TODO

Roadmap for the remaining build-out, requested 2026-10-20. Mirrors how
Scheduler's Admin page is organised (see its screenshot reviewed in chat).

## 1. Admin section (in progress)
Role-gated (`admin` only), tabbed single page at `/admin`, same visual
pattern as Scheduler's Admin screen.

- [x] Admin shell + tab navigation
- [x] SQL / ERP Connection tab -- test connection, sync items/colours now,
      show last-synced counts/timestamps (wraps `services/erp_sync.py`)
- [x] Reasons tab -- CRUD for `rework_reasons`
- [x] Door Types tab -- CRUD for `door_types`
- [x] Work Centres tab -- CRUD for `work_centres`
- [x] Colours tab -- swatches, real code/Dulux/base-colour columns, sortable,
      search + active/inactive state
- [x] Door Codes tab -- maps CPQ door codes to Door Types for the SO-lookup
      autofill (see section 5); also lists unmapped codes seen on real orders
- [x] Items tab -- `rule` is the only editable field (rest is ERP-owned).
      ~~Rates~~ -- labour-rate tracking is on hold, tab simplified accordingly
- [x] Scheduled Sync -- Daily/Weekly/Monthly auto-sync alongside the manual
      Sync buttons, background thread checked every 30 minutes
- [x] Users tab -- list/create/set role/active/reset password (same as
      Scheduler's Users tab)

## 2. Historical backfill
- [x] `import_rework_log.py` -- imported the real workbook's 12,343-row
      `REWORK` table: 11,961 landed, 199 skipped (missing a required field,
      ~1.6%), dedup is a SHA-256 of each row's raw values
      (`rework_events.source_row_hash`)
- [x] Turret sheet, all 3 standalone `Turret Sheet Audit YYYY.xlsx` workbooks
      -- into `turret_events`, viewable at `/turret`. Scrap-only (2026-10-21
      decision): most rows are just job-sheet-usage with nothing scrapped
      and are skipped. 2026: 382 inserted (confirmed 2026-10-21). 2025: 327
      inserted, same column layout as 2026 (confirmed 2026-10-22). 2024: 596
      inserted, using a separate older column layout -- no Week column, one
      shared Scrap Date instead of per-slot dates (confirmed 2026-10-22, see
      CLAUDE.md "Turret log" for the full breakdown). 1,305 scrap rows total
      across all three years. The *old combined* workbook's own 2025
      `Turret` tab (`2023-2026 Rework Data.xlsx`, a different source, 5,735
      rows) is still not imported -- see CLAUDE.md "Not yet done".

## 3. Import from Excel (ongoing, while the spreadsheet is still in use)
- [x] Admin-only upload page (`/import`): re-upload the same workbook, or a
      newer export of it, at any time -- confirmed live that a repeat upload
      of the full workbook reports 0 inserted / 12,019 already-imported with
      the row count unchanged, i.e. genuinely safe to run repeatedly.

## 4. Dashboard / reporting
Replacing the spreadsheet's pivot sheets.
- [x] Weekly/monthly rework count + cost trend
- [x] Top reasons (count + cost)
- [x] Colour / door-type breakdown
- [x] Period picker extended to 2 years / All time (2026-10-23) -- real
      history goes back to Jan 2023, so the old 365-day cap left most of it
      unreachable; confirmed live, "All time" correctly shows all 11,961
      historical entries. `services/reporting.py` now takes `days=None` to
      mean no lower bound at all, same shape across every function.

## 5. Sales Order lookup on the entry form
- [x] Enter an SO number -> auto-fills Job Number (reference), Height, Width,
      Colour, and (where `cpq_door_codes` has a mapping) Door Type
- [x] Product Code scoped to that job's real materials (`jobmatl_mst`)
      instead of a free-text search of the whole item master
- [x] Scrap Entire Door uses the real total material cost of everything on
      the job (`SUM(matl_qty * cost)` across every material line), not a
      single part's standard cost -- re-derived live server-side on save,
      never trusted from the client
- [x] Admin -> Door Codes for mapping CPQ codes to Door Types, seeded with
      only the confirmed-safe codes; flags unmapped codes seen on real orders

## 6. Scrap write-off tabs + ERP reconciliation (2026-10-21)
- [x] Turret -> Scrap write-off tab: weekly summary grouped by item, with
      the write-off-week offset shown ("From week(s)")
- [x] Doors (Rework log) -> Scrap write-off tab: same idea, derived weekly
      instead of using a pre-entered week column, since web-form entries
      have no such field; grouped by product code (not product code+type)
      since the ERP write-off doesn't care why something was scrapped
- [x] ERP reconciliation for both: department provided the real Power Query
      source behind their own write-off pivots (`matltran_mst`,
      `reason_code='SCR'`), confirmed live and wired in -- "ERP actual"
      shows a real match/mismatch per item/week now, not a placeholder. See
      CLAUDE.md, "ERP scrap reconciliation".

## 7. Turret entry form (2026-10-21)
Web form for logging turret jobs directly, replacing the Excel sheet as the
source going forward. All 3 material slots (and their rework counterparts)
are constrained to Sheet items -- confirmed: "Turret only deals with sheet."
Two-stage: create the job-materials entry first (`event_date`), reopen the
same row later via `/turret/<id>/edit` to add rework/scrap, which stamps
`scrap_date_a/b/c` to the day it's actually added (not re-stamped on later
re-saves). `turret_events.type` renamed to `door_type` (it already held
door-family data like "Plasma"/"Classic", not a replace-vs-rework
distinction); new `rework_type` column holds that ("Replacement Parts" /
"Rework Entire Door"). Reason reuses Doors' shared `rework_reasons` list
(2026-10-22) -- originally its own separate `turret_reasons` table + Admin
tab (2026-10-21), reversed the next day: the department asked for the
shared list instead, so that table/tab are gone (migration 0011; it never
held real data, nothing to migrate).
- [x] Schema migration (colour, door_type rename, rework_type, reason)
- [x] New entry form + edit/reopen flow -- confirmed live end-to-end
- [x] Material 1/2 (+ Rework material 1/2) scope to the job's real BOM via
      the SO lookup; slot 3 ("Other") always offers the full Sheet list
- [x] Sheet classification switched from a hand-curated list to a real ERP
      field (`items.plan_code = 'SHT'`, synced via migration 0010) -- no
      more guessing from item descriptions. 9 real sheet items now resolve
      automatically instead of 5. See CLAUDE.md, "Turret entry form".
- [x] `3902210.1.2` had no `plan_code` set in SyteLine at all -- fixed on the
      ERP side (2026-10-22, set to `SHT`), confirmed live and synced in:
      10 Sheet items now resolve automatically instead of 9, no app changes
      needed since Turret's material dropdowns and Doors' write-off
      exclusion both already derive from `items.plan_code = 'SHT'`.

## 8. Admin polish (requested 2026-10-21, done 2026-10-22)
- [x] Reasons tab -- inline edit for existing rows, identified by `id` so a
      typo'd reason/code/source/fault_category can be fixed after the fact;
      renaming the reason text cascades into every historical rework_events/
      turret_events row that used the old wording (confirmed live).
- [x] Door Codes tab -- switched back from "every row is a live input" to
      read-only rows + a per-row Edit button (reverses the 2026-10-20
      decision), reusing the same `.view-val`/`.edit-val`/`editing` CSS
      pattern now also used by Reasons, rather than inventing a second one.
- [x] Work Centres -- added a `sort_order` column (already existed in the
      schema, just wasn't exposed/editable) with a Save-order action per
      row; the entry form's dropdown and the Admin table both already
      `ORDER BY sort_order, name`, so this took effect in both places
      immediately, no further wiring needed.

## Not in this pass (see CLAUDE.md "Not yet done" for the full list)
- 2025 Turret history (old workbook's own `Turret` tab) -- not imported
- "Scrap Entire Door" / item "Door" isn't reconciled against ERP yet (the
  Doors write-off tab only covers Replace Part/Rework-Recoat so far)

~~Length-charting tables~~ -- resolved: checked live, `emdaLengthCharts`/
`emdaLengths`/`emdaLengthChartKey` are empty and unused. Nothing to build.
