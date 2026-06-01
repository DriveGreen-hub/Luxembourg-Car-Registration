# Lëtzebuerg Auto — Luxembourg new-vehicle registration dashboard

An interactive, self-updating dashboard for **new vehicle registrations in
Luxembourg**, built on the open [Parc Automobile du Luxembourg][src] dataset
(Société Nationale de Circulation Automobile, licence CC0).

It replaces the manual monthly chart with a filterable view:

- **Periods** — focus month, year-to-date, rolling 12 months, full history,
  with **MoM** and **YoY** deltas computed automatically.
- **Segments** — passenger cars · vans · buses.
- **Type** — brand-new vs used import (and both).
- **Breakdowns** — by manufacturer, model and drivetrain
  (BEV / PHEV / HEV / Petrol / Diesel / Other).
- **Model trend** — pick any model and see its monthly registration curve.
- **CO₂ intensity** — registration-weighted average CO₂ (g/km, WLTP) over time,
  plus an Avg CO₂ KPI and a per-model CO₂ column in the table.
- **Exports** — CSV of the current breakdown, PNG of the trend chart.

No build step, no framework, no external JS — a single `index.html` with
hand-drawn SVG charts that reads one small JSON file.

[src]: https://data.public.lu/fr/datasets/parc-automobile-du-luxembourg/

---

## How it works

The published dataset is a **stock snapshot** — every vehicle currently on the
road (~170 MB XLSX / ~840 MB XML per month), *not* a feed of monthly
registrations. `build_data.py` reconstructs the registration flow from the
date fields on each vehicle:

| Field | Meaning |
|---|---|
| `DATCIR_GD` | first registration in Luxembourg → the **month bucket** |
| `DATCIRPRM` | first registration anywhere |
| `CATSTC` | national category → segment (car=1, van=32/33, bus=71–76) |
| `LIBMRQ` / `TYPCOM` | manufacturer / model |
| `LIBCRB` + `AUTOELEC`/`CONSELEC` | fuel → drivetrain |
| `CO2WLTP` (fallback `INFCO2`) | CO₂ g/km → emissions view |

Classification:

- **Brand-new** — `DATCIRPRM == DATCIR_GD` (first-ever registration was in LU).
- **Used import** — `DATCIRPRM < DATCIR_GD` (registered abroad first).

The result is aggregated to `(month, segment, type, brand, model, drivetrain)`
and written, integer-coded, to `data/registrations.json` (a few hundred KB).
The dashboard does all slicing client-side.

> **Caveat — survivorship bias.** A single snapshot only contains vehicles
> *still on the road*, so months far in the past are slightly undercounted
> (scrapped/exported cars are gone). Recent months are accurate. The GitHub
> Action runs monthly with `--append`, so each freshly-completed month is
> captured at full accuracy and history stops drifting going forward.

---

## Quick start (local)

```bash
# 1. install deps for the pipeline
pip install requests openpyxl

# 2. pull the latest snapshot and build the data file
python build_data.py --months 72

# 3. serve the dashboard (fetch() needs http://, not file://)
python -m http.server 8080
# open http://localhost:8080
```

Don't want to download 170 MB yet? The repo ships with synthetic sample data
so the dashboard works immediately — just run step 3, or regenerate it with
`python make_sample_data.py`.

---

## Deploy to GitHub Pages (auto-updating)

The included workflow `.github/workflows/deploy.yml` both **rebuilds the data**
(monthly) and **deploys the site** to GitHub Pages — no branch juggling.

**One-time setup**

1. Create an empty repo on GitHub (e.g. `lux-cars`). Then, from this folder:

   ```bash
   git init
   git add .
   git commit -m "Luxembourg registration dashboard"
   git branch -M main
   git remote add origin https://github.com/<you>/lux-cars.git
   git push -u origin main
   ```

2. On GitHub: **Settings → Pages → Build and deployment → Source: GitHub Actions.**

3. **Actions → Build data & deploy to Pages → Run workflow** (first run pulls the
   real ~170 MB snapshot, builds `data/registrations.json`, and publishes).

Your site goes live at `https://<you>.github.io/lux-cars/`.

**After that, it maintains itself:**

| Trigger | What happens |
|---|---|
| You `git push` | site redeploys with the current data (no heavy download) |
| 8th of each month | downloads the new SNCA snapshot, `--append`s the freshly-completed month, commits, redeploys |
| Manual "Run workflow" | same as the monthly run, on demand |

The dashboard loads `data/registrations.json` if present and falls back to the
inline sample otherwise, so it never shows a blank page.

---

## Files

| File | Purpose |
|---|---|
| `index.html` | the dashboard (self-contained) |
| `data/registrations.json` | aggregated data the dashboard reads |
| `build_data.py` | downloads + aggregates the real SNCA snapshot |
| `make_sample_data.py` | regenerates the synthetic demo data |
| `.github/workflows/deploy.yml` | monthly data refresh + Pages deploy |

## Common tweaks

- **Add/adjust drivetrain rules** → `classify_drivetrain()` in `build_data.py`.
- **Change segment mapping** (e.g. include motorcycles) → `SEGMENT_BY_CAT`.
- **Use the XML export instead of XLSX** → `build_data.py --file parc.xml`
  (streamed with `iterparse`, lower memory).
- **Longer history without drift** → run monthly with `--append` (the workflow
  already does), or process several archived snapshots.

Data © SNCA, distributed under CC0 via data.public.lu.
