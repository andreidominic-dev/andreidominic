# Portfolio demo pages

Five self-contained demo pages that stand in for the internal back-office tools.
Every page is plain HTML with inline CSS and JavaScript: no build step, no
dependencies, no network requests, no storage.

## Files

| File | Replaces | What it shows |
|---|---|---|
| `home.html` | backoffice.html | Attention banner, pending cases, internal references (expand + search), task cards |
| `dashboard.html` | dashboard.html | Executive summary, proportional bar, per-task totals, web-orders totals, average toggle, daily chart |
| `follow-up.html` | follow-up.html | In Progress / Posted tabs, search, four stat cards, entries table |
| `web-orders.html` | web-orders.html | Entries table, daily averages, order-mix donut, all-time totals, daily + weekly trend charts |
| `barcode-lookup.html` | barcode_lookup_tool.html | Exact lookup, smart search, accessories UPC against a fake catalogue |

Open any file directly (`file://` works) or put the folder on the site and open
`home.html` inside the modal iframe. Demos link to each other with relative
links (`home.html`, `dashboard.html`, …), so the folder must keep these names.

## How to edit the fake data

All data lives in one plain object near the top of each page's `<script>` block.

- **home.html** — `DEMO` holds `summary` (the two attention counts and the
  pending-case count), `pendingCases` (case number, date, folder),
  `references` (groups and document names) and `taskGroups` (cards, with `href`
  only for pages that exist as demos).
- **dashboard.html** — `SEED`, `START` and `END` define the daily web-orders
  series that is generated at load time; `TASKS` holds the seven per-task
  totals. The web-orders figure is filled in from the generated series, so
  totals and the proportional bar always agree.
- **follow-up.html** — `ENTRIES` is the table: assignee, web order number, date
  received, case number, follow-up type, remarks, status and timestamps.
  `DEMO_NOW` freezes "today" so the stat cards read the same for every visitor.
- **web-orders.html** — the same `SEED` / `START` / `END` daily generator as the
  dashboard, plus the per-row `remarks`. Change the seed here and in
  `dashboard.html` together to keep the two pages consistent.
- **barcode-lookup.html** — `MODELS`, `SIZES`, `COLOURS`, `TEMPLE_LENGTHS`,
  `TEMPLE_BUSHES`, `TEMPLE_TYPES`, `VARIANTS` and `SEED` build the catalogue
  (`CATALOGUE`, ~412 rows). `ACCESSORY_LANGUAGES` holds the accessory barcodes
  and base quantities used by the Accessories UPC tab.

Everything is deterministic: the same seed produces the same numbers for every
visitor. Nothing is saved — status changes, remarks and any other edit live in
memory only and disappear on reload.

## Blurred fields

`.pii { filter: blur(7px); user-select: none; pointer-events: none; }` is
defined in every page and applied to the fields that look sensitive in the
screenshots: assignees, web order numbers and case numbers. The values behind
the blur are invented. Product IDs and barcodes in the barcode tool are not
blurred.

## Exports

"Export to CSV" buttons build a CSV in the browser and download it with a blob
URL. If the embedding iframe blocks downloads, the page shows a toast instead.
No spreadsheet library is used.

## Design notes

Colours, type scale, spacing and card shapes follow the source tools: the warm
"Caramel Coated" palette for home, follow-up and web orders, the ivory/gold
dashboard, and the light blue-grey barcode tool. Fonts are system stacks only —
no webfonts are loaded.
