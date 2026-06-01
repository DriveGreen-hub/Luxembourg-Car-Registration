#!/usr/bin/env python3
"""
build_data.py — Luxembourg new-vehicle registration pipeline
============================================================
Turns the monthly "Parc Automobile du Luxembourg" fleet snapshot (a ~170 MB
XLSX / ~840 MB XML export of *every* registered vehicle) into the small,
integer-coded JSON the dashboard reads (data/registrations.json).

HOW REGISTRATION FLOWS ARE DERIVED FROM A STOCK SNAPSHOT
--------------------------------------------------------
The open dataset is a *stock* (all vehicles currently on the road), not a
*flow* of monthly registrations. Each vehicle row carries the dates we need:

  DATCIRPRM  date of first registration anywhere
  DATCIR_GD  date of first registration in Luxembourg
  OPE        last operation code (N=new, I=import, T=transfer, ...)

We reconstruct monthly flows by bucketing each vehicle on the month of
DATCIR_GD (when it entered the LU fleet) and classifying:

  brand-new  -> DATCIRPRM == DATCIR_GD   (first-ever registration was in LU)
  import     -> DATCIRPRM <  DATCIR_GD   (was registered abroad first)

CAVEAT (survivorship bias): a single current snapshot only contains vehicles
still on the road, so counts for months far in the past are slightly
undercounted (scrapped/exported cars are gone). It is accurate for recent
months. For a bias-free long history, run this each month and keep appending
the freshly-completed month (see --append), or process several archived
snapshots.

USAGE
-----
  pip install requests openpyxl
  python build_data.py                      # latest snapshot, full reconstruction
  python build_data.py --months 60          # keep only last 60 months in output
  python build_data.py --file path.xlsx     # use an already-downloaded file
  python build_data.py --append             # merge freshly-completed month into
                                            #   existing data/registrations.json
"""
import argparse, json, os, re, sys, datetime as dt
from collections import defaultdict

DATASET_API = "https://data.public.lu/api/1/datasets/59cbac9f111e9b6be027c292/"
CACHE = "cache"
OUT = "data/registrations.json"

DRIVETRAINS = ["BEV", "PHEV", "HEV", "Petrol", "Diesel", "Other"]

# ---- national category (CATSTC) -> dashboard segment -----------------------
SEGMENT_BY_CAT = {}
for c in [1]:                         SEGMENT_BY_CAT[c] = "car"      # Voiture
for c in [32, 33]:                    SEGMENT_BY_CAT[c] = "van"      # utilitaire, camionnette
for c in [71, 72, 73, 74, 75, 76]:    SEGMENT_BY_CAT[c] = "bus"      # autocars / autobus
# everything else (trucks, trailers, motorcycles, tractors...) is ignored


def classify_drivetrain(libcrb, autoelec, conselec):
    """Map fuel label + electric fields to a drivetrain bucket."""
    s = (libcrb or "").upper()
    has_elec_range = _num(autoelec) > 0 or _num(conselec) > 0
    if any(k in s for k in ("RECHARGEABLE", "PLUG-IN", "PLUG IN", "HYBRIDE RECH")):
        return "PHEV"
    if "ELEC" in s or s in ("BEV", "EV"):
        return "BEV"
    if "HYBRID" in s or "HYBRIDE" in s:
        # plug-in hybrids sometimes only flagged via electric range
        return "PHEV" if has_elec_range else "HEV"
    if "ESSENCE" in s or "PETROL" in s or "BENZIN" in s:
        return "Petrol"
    if "DIESEL" in s or "GASOIL" in s or "GAZOLE" in s:
        return "Diesel"
    # LPG, CNG, hydrogen, ethanol, unknown...
    return "Other"


def _num(x):
    try:
        return float(str(x).replace(",", ".").strip())
    except Exception:
        return 0.0


def _parse_date(x):
    """SNCA dates look like dd/mm/YYYY (sometimes ISO). Return date or None."""
    if not x:
        return None
    x = str(x).strip()
    if not x:
        return None
    for f in ("%d/%m/%Y", "%Y-%m-%d", "%d.%m.%Y", "%Y%m%d"):
        try:
            return dt.datetime.strptime(x[:10], f).date()
        except ValueError:
            continue
    return None


# ============================ download ======================================
def resolve_latest_xlsx():
    import requests
    print("· querying dataset API for the latest snapshot…")
    r = requests.get(DATASET_API, timeout=60)
    r.raise_for_status()
    res = r.json().get("resources", [])
    best = None
    for it in res:
        title = (it.get("title") or "")
        m = re.search(r"(\d{6})", title)
        if title.lower().endswith(".xlsx") and m:
            ym = m.group(1)
            if best is None or ym > best[0]:
                best = (ym, it["url"], title)
    if not best:
        sys.exit("Could not find an XLSX resource in the dataset.")
    print(f"· latest: {best[2]}  ({best[0]})")
    return best


def download(url, dest):
    import requests
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    if os.path.exists(dest) and os.path.getsize(dest) > 1_000_000:
        print(f"· using cached {dest}")
        return dest
    print(f"· downloading {url}")
    with requests.get(url, stream=True, timeout=600) as r:
        r.raise_for_status()
        done = 0
        with open(dest, "wb") as f:
            for chunk in r.iter_content(1 << 20):
                f.write(chunk)
                done += len(chunk)
                print(f"\r  {done/1e6:6.1f} MB", end="")
    print()
    return dest


# ============================ parse =========================================
def iter_rows_xlsx(path):
    """Stream rows from the (single-sheet) XLSX, yielding dicts keyed by header."""
    from openpyxl import load_workbook
    wb = load_workbook(path, read_only=True, data_only=True)
    ws = wb[wb.sheetnames[0]]
    rows = ws.iter_rows(values_only=True)
    header = [str(h).strip() if h is not None else "" for h in next(rows)]
    idx = {h: i for i, h in enumerate(header)}
    need = ["CATSTC", "LIBMRQ", "TYPCOM", "LIBCRB",
            "DATCIRPRM", "DATCIR_GD", "AUTOELEC", "CONSELEC",
            "CO2WLTP", "INFCO2"]
    missing = [c for c in need if c not in idx]
    if missing:
        print(f"! warning: columns not found: {missing}\n  headers seen: {header[:40]}")
    def get(row, col):
        i = idx.get(col)
        return row[i] if i is not None and i < len(row) else None
    for row in rows:
        if row is None:
            continue
        yield {c: get(row, c) for c in need}
    wb.close()


def iter_rows_xml(path):
    """Stream rows from the XML export with iterparse (memory-light)."""
    import xml.etree.ElementTree as ET
    need = ["CATSTC", "LIBMRQ", "TYPCOM", "LIBCRB",
            "DATCIRPRM", "DATCIR_GD", "AUTOELEC", "CONSELEC",
            "CO2WLTP", "INFCO2"]
    rec = {}
    for ev, el in ET.iterparse(path, events=("end",)):
        if el.tag in need:
            rec[el.tag] = el.text
        elif el.tag.lower() == "vehicle":
            yield {c: rec.get(c) for c in need}
            rec = {}
            el.clear()


def iter_rows(path):
    return iter_rows_xml(path) if path.lower().endswith(".xml") else iter_rows_xlsx(path)


# ============================ aggregate =====================================
def build(path, snapshot_ym, keep_months=None):
    counts = defaultdict(int)         # (ym, seg, op, brand, model, dt) -> n
    co2sum = defaultdict(float)       # same key -> sum of CO2 (g/km)
    co2n = defaultdict(int)           # same key -> vehicles with a known CO2
    n_read = n_kept = 0
    for v in iter_rows(path):
        n_read += 1
        if n_read % 100000 == 0:
            print(f"\r  parsed {n_read:,} rows…", end="")
        try:
            cat = int(_num(v.get("CATSTC")))
        except Exception:
            continue
        seg = SEGMENT_BY_CAT.get(cat)
        if seg is None:
            continue
        d_lu = _parse_date(v.get("DATCIR_GD"))
        if d_lu is None:
            continue
        ym = f"{d_lu.year:04d}-{d_lu.month:02d}"
        d_first = _parse_date(v.get("DATCIRPRM")) or d_lu
        op = "new" if d_first >= d_lu else "import"
        brand = (v.get("LIBMRQ") or "UNKNOWN").strip().title() or "UNKNOWN"
        model = (v.get("TYPCOM") or "").strip().upper() or "—"
        dtrain = classify_drivetrain(v.get("LIBCRB"), v.get("AUTOELEC"), v.get("CONSELEC"))
        key = (ym, seg, op, brand, model, dtrain)
        counts[key] += 1
        # CO2: prefer WLTP, fall back to combined; BEV is a known 0.
        co2 = _num(v.get("CO2WLTP")) or _num(v.get("INFCO2"))
        if dtrain == "BEV":
            co2sum[key] += 0.0; co2n[key] += 1
        elif co2 > 0:
            co2sum[key] += co2; co2n[key] += 1
        n_kept += 1
    print(f"\r  parsed {n_read:,} rows · {n_kept:,} cars/vans/buses kept")

    months = sorted({k[0] for k in counts})
    if keep_months:
        months = months[-keep_months:]
    mset = set(months)
    months_i = {m: i for i, m in enumerate(months)}
    segs = ["car", "van", "bus"]; ops = ["new", "import"]
    brands, b_i = [], {}
    models, m_i = [], {}
    rows = []
    for (ym, seg, op, brand, model, dtrain), n in counts.items():
        if ym not in mset:
            continue
        if brand not in b_i:
            b_i[brand] = len(brands); brands.append(brand)
        mk = (b_i[brand], model)
        if mk not in m_i:
            m_i[mk] = len(models); models.append([model, b_i[brand]])
        key = (ym, seg, op, brand, model, dtrain)
        rows.append([months_i[ym], segs.index(seg), ops.index(op),
                     b_i[brand], m_i[mk], DRIVETRAINS.index(dtrain), n,
                     int(round(co2sum[key])), co2n[key]])

    return {
        "meta": {
            "generated": dt.date.today().isoformat(),
            "source": "Parc Automobile du Luxembourg (SNCA) via data.public.lu — CC0",
            "source_snapshot": snapshot_ym,
            "latest_month": months[-1] if months else None,
            "note": "Brand-new = first LU registration equals first-ever registration. "
                    "Import = vehicle previously registered abroad. Older months are "
                    "subject to survivorship bias (reconstructed from one stock snapshot).",
        },
        "dims": {"months": months, "segments": segs, "operations": ops,
                 "drivetrains": DRIVETRAINS, "brands": brands, "models": models},
        "rows": rows,
    }


def write(obj):
    os.makedirs("data", exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(obj, f, separators=(",", ":"), ensure_ascii=False)
    print(f"· wrote {OUT}  ({os.path.getsize(OUT)/1024:.0f} KB · "
          f"{len(obj['rows'])} rows · {len(obj['dims']['months'])} months)")


# ============================ main ==========================================
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--file", help="use a local xlsx/xml instead of downloading")
    ap.add_argument("--months", type=int, default=None, help="keep only the last N months")
    ap.add_argument("--append", action="store_true",
                    help="merge the freshly-completed month into existing output")
    args = ap.parse_args()

    if args.file:
        path = args.file
        m = re.search(r"(\d{6})", os.path.basename(path))
        snapshot = m.group(1) if m else "local"
    else:
        ym, url, _ = resolve_latest_xlsx()
        path = download(url, os.path.join(CACHE, f"parc-{ym}.xlsx"))
        snapshot = ym

    obj = build(path, snapshot, keep_months=args.months)

    if args.append and os.path.exists(OUT):
        obj = merge_append(json.load(open(OUT, encoding="utf-8")), obj)

    write(obj)


def merge_append(old, new):
    """Replace overlapping months in `old` with `new`'s values, keep history."""
    def explode(o):
        d = o["dims"]; out = defaultdict(lambda: [0, 0, 0])  # [n, co2sum, co2n]
        for r in o["rows"]:
            key = (d["months"][r[0]], d["segments"][r[1]], d["operations"][r[2]],
                   d["brands"][r[3]], d["models"][r[4]][0], d["drivetrains"][r[5]])
            out[key][0] += r[6]
            out[key][1] += r[7] if len(r) > 7 else 0
            out[key][2] += r[8] if len(r) > 8 else 0
        return out
    om, nm = explode(old), explode(new)
    new_months = {k[0] for k in nm}
    merged = {k: v for k, v in om.items() if k[0] not in new_months}
    merged.update(nm)
    # rebuild compact structure
    months = sorted({k[0] for k in merged})
    segs = ["car", "van", "bus"]; ops = ["new", "import"]
    mi = {m: i for i, m in enumerate(months)}
    brands, bi = [], {}; models, midx = [], {}; rows = []
    for (ym, seg, op, brand, model, dtr), vals in merged.items():
        if brand not in bi:
            bi[brand] = len(brands); brands.append(brand)
        mk = (bi[brand], model)
        if mk not in midx:
            midx[mk] = len(models); models.append([model, bi[brand]])
        rows.append([mi[ym], segs.index(seg), ops.index(op), bi[brand],
                     midx[mk], DRIVETRAINS.index(dtr), vals[0], vals[1], vals[2]])
    new["dims"] = {"months": months, "segments": segs, "operations": ops,
                   "drivetrains": DRIVETRAINS, "brands": brands, "models": models}
    new["rows"] = rows
    new["meta"]["latest_month"] = months[-1]
    return new


if __name__ == "__main__":
    main()
