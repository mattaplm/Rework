# Colour Library — ERP query and table layout

The active colour list from SyteLine (`emdaColour`), and a self-contained table
layout for it: swatch, search, hide-no-RGB toggle, click-to-sort headers.
Verified against the live ERP on 2026-10-20: 500 active colours, one row per
colour code.

## Query

```sql
SELECT
    c.Colour,
    c.ColourDescription,
    c.DuluxCode,
    c.RGB,
    c.BaseColour,
    b.ColourDescription AS BaseColourDescription,
    c.Door
FROM alpac_App.dbo.emdaColour AS c WITH (NOLOCK)
LEFT JOIN alpac_App.dbo.emdaColour AS b WITH (NOLOCK)
    ON b.Colour = c.BaseColour AND b.Obsolete = 0
WHERE c.Obsolete = 0
ORDER BY c.ColourDescription
```

`WHERE Obsolete = 0` limits it to active colours. The self-join looks up the
base colour's name, so no extra code is needed for that column.

## Columns

| Column | Meaning | Notes |
|---|---|---|
| `Colour` | Colour code, e.g. `T24`, `MA`, `AP` | The key. Sales-order lines reference it (`uf_emdaColourInside` / `uf_emdaColourOutside`, and the backing / sheet-detail colour fields). |
| `ColourDescription` | Display name, e.g. `KINETIC COPPER - BaseCoat Z60` | |
| `DuluxCode` | Dulux product code | Often blank. |
| `RGB` | Text `"R,G,B"`, e.g. `115,90,70` | 363 of 500 colours have it. Parse to hex for the swatch. |
| `BaseColour` | Code of the base colour | Used by woodgrain and metallic finishes (e.g. `WDR` = Woodgrain Dark Red). Blank for solid colours. |
| `BaseColourDescription` | Name of that base colour | From the self-join. |
| `Door` | Door flag (int) | Currently `0` on every active colour. |

## Layout

Single page, no dependencies. Replace `COLOURS` with the query rows as JSON,
using the raw column names above. Includes search (name, code or Dulux code),
a "Hide colours with no RGB" toggle, click-to-sort headers (blanks always sort
last) and a row count.

```html
<div class="colour-lib">
  <div class="cl-toolbar">
    <input type="text" id="cl-search" placeholder="Search colour, code or Dulux code…">
    <label><input type="checkbox" id="cl-hide-blank"> Hide colours with no RGB</label>
    <span id="cl-count"></span>
  </div>
  <div class="cl-wrap">
    <table class="cl-table">
      <thead id="cl-head"></thead>
      <tbody id="cl-body"></tbody>
    </table>
  </div>
</div>

<style>
  .colour-lib { font-family: Arial, sans-serif; color: #1e293b; }
  .cl-toolbar { display: flex; gap: 10px; align-items: center; flex-wrap: wrap; margin-bottom: 12px; font-size: .8rem; color: #475569; }
  .cl-toolbar input[type=text] { max-width: 280px; padding: 6px 10px; border: 1px solid #cbd5e1; border-radius: 6px; font-size: .85rem; }
  .cl-toolbar label { display: flex; align-items: center; gap: 6px; }
  #cl-count { color: #64748b; }
  .cl-wrap { overflow-x: auto; border: 1px solid #e2e8f0; border-radius: 10px; }
  .cl-table { width: 100%; border-collapse: collapse; font-size: .82rem; }
  .cl-table th { background: #f8fafc; color: #4338ca; font-weight: 600; font-size: .75rem; padding: 9px 10px;
                 text-align: left; white-space: nowrap; border-bottom: 1px solid #cbd5e1; position: sticky; top: 0;
                 cursor: pointer; user-select: none; }
  .cl-table th:hover { color: #4338ca; text-decoration: underline; }
  .cl-table td { padding: 7px 10px; border-bottom: 1px solid #e2e8f0; white-space: nowrap; vertical-align: middle; }
  .cl-table tbody tr:hover { background: #f1f5f9; }
  .cl-table tbody tr:last-child td { border-bottom: none; }
  .cl-swatch { display: inline-block; width: 16px; height: 16px; border-radius: 3px;
               border: 1px solid rgba(0,0,0,.15); vertical-align: middle; }
</style>

<script>
const COLOURS = [ /* rows from the query, e.g.
  { Colour: "T24", ColourDescription: "KINETIC COPPER - BaseCoat Z60", DuluxCode: null,
    RGB: "165,110,85", BaseColour: "EQ", BaseColourDescription: "COPPER PEARL MATT 20P4137M", Door: 0 }, */ ];

const COLUMNS = [
  { key: "ColourDescription",     label: "Colour" },
  { key: "Colour",                label: "Code" },
  { key: "DuluxCode",             label: "Dulux Code" },
  { key: "Door",                  label: "Door" },
  { key: "BaseColour",            label: "Base Colour" },
  { key: "BaseColourDescription", label: "Base Colour Desc" },
  { key: "RGB",                   label: "RGB" },
];
let sortCol = null, sortDir = "asc";

const esc = v => String(v ?? "").replace(/[&<>"']/g, ch =>
  ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[ch]));

// ERP "R,G,B" -> "#RRGGBB", or "" if blank/invalid
function rgbToHex(rgb) {
  const p = String(rgb ?? "").split(",").map(s => parseInt(s.trim(), 10));
  return p.length === 3 && p.every(v => v >= 0 && v <= 255)
    ? "#" + p.map(v => v.toString(16).padStart(2, "0")).join("").toUpperCase() : "";
}

// Blanks sort last in either direction
function sorted(rows) {
  if (!sortCol) return rows;
  return [...rows].sort((a, b) => {
    const va = String(a[sortCol] ?? "").toLowerCase(), vb = String(b[sortCol] ?? "").toLowerCase();
    if (!va && !vb) return 0; if (!va) return 1; if (!vb) return -1;
    return sortDir === "asc" ? va.localeCompare(vb, undefined, { numeric: true })
                             : vb.localeCompare(va, undefined, { numeric: true });
  });
}

function render() {
  const q = document.getElementById("cl-search").value.trim().toLowerCase();
  const hideBlank = document.getElementById("cl-hide-blank").checked;
  const rows = COLOURS.filter(c =>
    (!hideBlank || rgbToHex(c.RGB)) &&
    (!q || [c.ColourDescription, c.Colour, c.DuluxCode].some(v => String(v ?? "").toLowerCase().includes(q))));

  document.getElementById("cl-count").textContent = `${rows.length} of ${COLOURS.length} colours`;
  document.getElementById("cl-head").innerHTML = "<tr><th></th>" + COLUMNS.map(col =>
    `<th data-key="${col.key}">${col.label}${sortCol === col.key ? (sortDir === "asc" ? " ▲" : " ▼") : ""}</th>`
  ).join("") + "</tr>";
  document.getElementById("cl-body").innerHTML = sorted(rows).map(c => {
    const hex = rgbToHex(c.RGB);
    return `<tr>
      <td>${hex ? `<span class="cl-swatch" style="background:${hex}"></span>` : ""}</td>
      <td>${esc(c.ColourDescription)}</td>
      <td>${esc(c.Colour)}</td>
      <td>${esc(c.DuluxCode)}</td>
      <td>${Number(c.Door) ? "✓" : ""}</td>
      <td>${esc(c.BaseColour)}</td>
      <td>${esc(c.BaseColourDescription)}</td>
      <td>${esc(c.RGB)}</td>
    </tr>`;
  }).join("");
}

document.getElementById("cl-head").addEventListener("click", e => {
  const key = e.target.closest("th")?.dataset.key;
  if (!key) return;
  sortDir = sortCol === key && sortDir === "asc" ? "desc" : "asc";
  sortCol = key;
  render();
});
document.getElementById("cl-search").addEventListener("input", render);
document.getElementById("cl-hide-blank").addEventListener("change", render);
render();
</script>
```

The styling is the Scheduler's light theme (slate text, indigo headers, sticky
header row, hover highlight), with the colours hard-coded instead of the app's
CSS variables.
