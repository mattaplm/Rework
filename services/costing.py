"""Cost calculations, ported from the `REWORK` table's Excel formulas
(2023-2026 Rework Data.xlsx). Pure functions -- no DB/Flask access -- so they
can be unit tested and reused for both the live entry-form preview and the
authoritative server-side calc on save.

Original formulas (M column of the `Rework` table):
    QTY TO REMOVE = XLOOKUP(Product Code, SL_Items[Part Number], SL_Items[Rule]) * Quantity
    Cost          = 132  if R/T = "Rework / Recoat"
                    else  XLOOKUP(Product Code, SL_Items, Std Cost) * QTY TO REMOVE

PC (powder-coat) cost replaces that flat 132 (2026-11-11): `pc_rate` (Admin
-> Cost: PC flightbar rate + Powder, default $72 + $20) is charged on Rework /
Recoat and Replace Part, itemised separately from material cost. Rework /
Recoat has no material cost of its own now. It's a one-off per rework, not
x quantity -- and once per *entry* across its material lines, which the
caller (services.rework.create_events) handles by passing pc_rate=None for
every line after the first chargeable one.

Labour cost (the old sheet's "Cost 2" column, from per-part picking/cutting/
machining/assembly rates) is deliberately not computed here -- not in use for
now. `rework_events.labour_cost` stays in the schema for the historical rows
that already carry a real value from the spreadsheet import; new entries just
leave it NULL. See git history for the rate-based formula if this comes back.

`full_door_material_cost` (added 2026-10-20): when a Sales Order has been
looked up (services.erp_lookup.lookup_order) and the type is "Scrap Entire
Door", this replaces the single-item std_cost calc with the SUM of every real
material line on that job (`matl_qty x cost` per jobmatl_mst line) -- the
actual cost of everything that went into the door, not an estimate from one
part's standard cost. Ignored for any other type, since Replace Part/Rework
Recoat are genuinely about one part, not the whole door's material list.
"""

from __future__ import annotations

from dataclasses import dataclass

PC_COST_TYPES = ("Rework / Recoat", "Replace Part")


COMPONENTS = ("Stile", "Rail")


@dataclass
class CostResult:
    qty_to_remove: float | None
    material_cost: float | None
    pc_cost: float | None = None

    @property
    def total_cost(self) -> float:
        return (self.material_cost or 0) + (self.pc_cost or 0)


def compute_costs(
    rework_type: str,
    quantity: float,
    item: dict | None,
    full_door_material_cost: float | None = None,
    job_material_qty: float | None = None,
    pieces_per_door: int | None = None,
    pc_rate: float | None = None,
) -> CostResult:
    """`item` is a row from services.reference_data.get_item (or None if the
    product code isn't recognised) -- carries rule/std_cost.

    Qty to remove (2026-10-30): when the operator says what the part is
    (a stile or a rail) and we know both the job's own material qty for it
    (`job_material_qty`, from jobmatl_mst -- e.g. 1 length) and how many of
    that component one door has (`pieces_per_door`, set per CPQ code in
    Admin -> Door Codes -- e.g. 2 stiles), scrapping `quantity` pieces writes
    off that share of the material: job_material_qty x quantity / pieces.
    Anything else (no component, no job, pieces not set yet) falls back to
    the old per-item `rule` x quantity."""
    if pieces_per_door and job_material_qty is not None:
        qty_to_remove = round(float(job_material_qty) * quantity / pieces_per_door, 4)
    else:
        qty_to_remove = float(item["rule"]) * quantity if item and item.get("rule") is not None else None

    material_cost = None
    if rework_type == "Scrap Entire Door" and full_door_material_cost is not None:
        material_cost = full_door_material_cost
    elif rework_type == "Rework / Recoat":
        material_cost = None  # PC cost only (see module docstring)
    elif item and item.get("std_cost") is not None and qty_to_remove is not None:
        material_cost = float(item["std_cost"]) * qty_to_remove

    pc_cost = round(float(pc_rate), 2) if pc_rate is not None and rework_type in PC_COST_TYPES else None
    return CostResult(qty_to_remove=qty_to_remove, material_cost=material_cost, pc_cost=pc_cost)


def compute_sheet_scrap_cost(qty: float | None, item: dict | None) -> float | None:
    """Turret's scrap cost -- qty x std_cost directly, no `rule` multiplier
    (that's Doors' units-per-part concept for a cut part of a door; Turret
    scraps the raw sheet itself, so there's no further conversion needed).
    `item` is a services.reference_data.get_item row (or None if the sheet
    code isn't recognised)."""
    if qty is None or not item or item.get("std_cost") is None:
        return None
    return float(item["std_cost"]) * float(qty)
