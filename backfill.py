#!/usr/bin/env python3
"""
backfill.py — accurate full-history backfill for the Luxembourg dashboard
=========================================================================
Builds an accurate month-by-month history by processing EVERY monthly SNCA
snapshot and taking, from each, the freshly-completed month it represents best
(the month *before* the snapshot's publish month). Sourcing each month from the
snapshot taken right after it avoids the survivorship bias you get when you try
to reconstruct years of history from one recent snapshot.

It reuses the exact parsing + classification from build_data.py, so the numbers
match build_data.py and your monthly reports.

KEY PROPERTIES
  • Resumable  — months already in data/registrations.json are skipped, so you
                 can stop/restart freely (it processes oldest → newest).
  • Low disk   — each snapshot is downloaded to a temp file, parsed, deleted.
  • Honest     — only *complete* months are recorded (never the partial month
                 the snapshot was taken in).

USAGE
  pip install requests openpyxl
  python backfill.py                 # process all snapshots (long; ~100 files)
  python backfill.py --limit 12      # process only the next 12 unprocessed ones
  python backfill.py --from 2020-01  # ignore months before this
  python backfill.py --use-xml       # use the .xml export instead of .xlsx

After it finishes (or partway), commit data/registrations.json. The monthly
workflow then maintains it with --append.
"""
import argparse, json, os, re, sys, datetime as dt
from collections import defaultdict
import build_data as bd            # reuse validated parsing + classification


def list_snapshots(use_xml=False):
    import requests
    r = requests.get(bd.DATASET_API, timeout=60); r.raise_for_status()
    ext = ".xml" if use_xml else ".xlsx"
    out = {}
    for it in r.json().get("resources", []):
        title = (it.get("title") or "")
        m = re.search(r"(\d{6})", title)
        if title.lower().endswith(ext) and m:
            out[m.group(1)] = it["url"]          # YYYYMM -> url (dedupe)
    return sorted(out.items())                    # ascending by YYYYMM


def prev_month(yyyymm):
    y, mo = int(yyyymm[:4]), int(yyyymm[4:6])
    mo -= 1
    if mo == 0:
        y, mo = y - 1, 12
    return f"{y:04d}-{mo:02d}"


def aggregate_file(path, wanted_months):
    """Aggregate rows whose DATCIR_GD month is in `wanted_months`."""
    out = defaultdict(lambda: [0, 0, 0])          # key -> [n, co2sum, co2n]
    for v in bd.iter_rows(path):
        try:
            cat = int(bd._num(v.get("CATSTC")))
        except Exception:
            continue
        seg = bd.SEGMENT_BY_CAT.get(cat)
        if seg is None:
            continue
        d_lu = bd._parse_date(v.get("DATCIR_GD"))
        if d_lu is None:
            continue
        ym = f"{d_lu.year:04d}-{d_lu.month:02d}"
        if ym not in wanted_months:
            continue
        d_first = bd._parse_date(v.get("DATCIRPRM")) or d_lu
        op = bd.classify_operation(v.get("CODEOP"), d_first, d_lu)
        if op is None:
            continue
        brand = str(v.get("LIBMRQ") or "").strip().title() or "UNKNOWN"
        model = str(v.get("TYPCOM") or "").strip().upper() or "—"
        dtr = bd.classify_drivetrain(v.get("LIBCRB"), v.get("CODCRB"),
                                     v.get("AUTOELEC"), v.get("CONSELEC"))
        co2 = bd._num(v.get("CO2WLTP")) or bd._num(v.get("INFCO2"))
        key = (ym, seg, op, brand, model, dtr)
        out[key][0] += 1
        if dtr == "BEV":
            out[key][2] += 1
        elif co2 > 0:
            out[key][1] += co2; out[key][2] += 1
    return out


def load_master():
    """Load existing data/registrations.json. Returns (master, backfilled).
    All existing months are loaded (so nothing disappears mid-backfill), but
    only months listed in meta.backfilled count as 'accurately sourced' — the
    approximate build_data months get re-sourced and overwritten."""
    master = defaultdict(lambda: [0, 0, 0])
    backfilled = set()
    if os.path.exists(bd.OUT):
        o = json.load(open(bd.OUT, encoding="utf-8"))
        src = (o.get("meta", {}).get("source", "") or "").lower()
        if "synthetic" in src or "sample" in src:
            print("· ignoring existing sample data (starting clean).")
            return master, backfilled
        d = o["dims"]
        for r in o["rows"]:
            key = (d["months"][r[0]], d["segments"][r[1]], d["operations"][r[2]],
                   d["brands"][r[3]], d["models"][r[4]][0], d["drivetrains"][r[5]])
            master[key][0] += r[6]
            master[key][1] += r[7] if len(r) > 7 else 0
            master[key][2] += r[8] if len(r) > 8 else 0
        backfilled = set(o.get("meta", {}).get("backfilled", []))
        print(f"· loaded {len({k[0] for k in master})} existing months; "
              f"{len(backfilled)} already accurately backfilled")
    return master, backfilled


def write_master(master, snapshot_label, backfilled):
    months = sorted({k[0] for k in master})
    segs = ["car", "van", "bus"]; ops = ["new", "import"]
    mi = {m: i for i, m in enumerate(months)}
    brands, bi = [], {}; models, midx = [], {}; rows = []
    for (ym, seg, op, brand, model, dtr), vals in master.items():
        if vals[0] == 0:
            continue
        if brand not in bi:
            bi[brand] = len(brands); brands.append(brand)
        mk = (bi[brand], model)
        if mk not in midx:
            midx[mk] = len(models); models.append([model, bi[brand]])
        rows.append([mi[ym], segs.index(seg), ops.index(op), bi[brand],
                     midx[mk], bd.DRIVETRAINS.index(dtr), vals[0], vals[1], vals[2]])
    obj = {
        "meta": {
            "generated": dt.date.today().isoformat(),
            "source": "Parc Automobile du Luxembourg (SNCA) via data.public.lu — CC0",
            "source_snapshot": f"backfill→{snapshot_label}",
            "latest_month": months[-1] if months else None,
            "backfilled": sorted(backfilled),
            "note": "Each month sourced from the snapshot taken right after it "
                    "(accurate full-history backfill).",
        },
        "dims": {"months": months, "segments": segs, "operations": ops,
                 "drivetrains": bd.DRIVETRAINS, "brands": brands, "models": models},
        "rows": rows,
    }
    os.makedirs("data", exist_ok=True)
    with open(bd.OUT, "w", encoding="utf-8") as f:
        json.dump(obj, f, separators=(",", ":"), ensure_ascii=False)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=None, help="max snapshots to process this run")
    ap.add_argument("--from", dest="frm", default="2017-01", help="ignore months before YYYY-MM")
    ap.add_argument("--latest", action="store_true",
                    help="only add the newest snapshot's month (monthly maintenance)")
    ap.add_argument("--use-xml", action="store_true")
    args = ap.parse_args()

    snaps = list_snapshots(args.use_xml)
    if args.latest:
        snaps = snaps[-1:]                         # newest snapshot only
    print(f"· found {len(snaps)} snapshot(s) to consider"
          + (f" ({snaps[0][0]}…{snaps[-1][0]})" if snaps else ""))
    master, done = load_master()

    # Newest-first for bulk runs: corrects the most recent months first
    # (so the live dashboard is accurate immediately) and extends backward.
    order = snaps if args.latest else list(reversed(snaps))

    processed = 0
    for ym, url in order:
        target = prev_month(ym)                    # newest complete month in this snapshot
        if target < args.frm or target in done:
            continue
        if args.limit and processed >= args.limit:
            print("· hit --limit; stop (re-run to continue).")
            break
        ext = ".xml" if args.use_xml else ".xlsx"
        path = bd.download(url, os.path.join(bd.CACHE, f"parc-{ym}{ext}"))
        try:
            agg = aggregate_file(path, {target})
        except SystemExit as e:
            print(f"! skipping {ym}: {e}")
            if os.path.exists(path):
                os.remove(path)
            continue
        kept = sum(v[0] for v in agg.values())
        if agg:
            # overwrite this month with the freshly-sourced version
            for k in [k for k in master if k[0] == target]:
                del master[k]
            for k, v in agg.items():
                master[k] = [v[0], v[1], v[2]]
        else:
            print(f"  · {target}: no rows in this snapshot (kept existing).")
        done.add(target)
        write_master(master, ym, done)             # persist after each month (resumable)
        if os.path.exists(path):
            os.remove(path)
        processed += 1
        print(f"  ✓ {target}: {kept} registrations  (accurate months: {len(done)})")

    print(f"\n· done. processed {processed} month(s) this run; "
          f"{len(done)} accurate months total → {bd.OUT}")


if __name__ == "__main__":
    main()
