#!/usr/bin/env python3
"""
Monthly BEV registration report generator for the Luxembourg Car Registration
dashboard. Reads data/registrations.json and produces, for one month:

  * report_YYYY-MM.md   — social-ready text (matches the old posting format)
  * report_YYYY-MM.html — a polished, dark-themed one-pager with charts

Usage:
  python make_report.py                # latest month in the data
  python make_report.py --month 2026-05
  python make_report.py --data data/registrations.json --out .
"""
import argparse, json, os, datetime as dt
from collections import Counter, defaultdict

PRETTY = {"Bmw":"BMW","Vw":"Volkswagen","Mg":"MG","Ds":"DS","Byd":"BYD",
          "Gwm":"GWM","Dfsk":"DFSK","Kg Mobility":"KG Mobility","Ora":"ORA",
          "Mercedes-Benz":"Mercedes-Benz","Ineos":"INEOS"}
def brand(b): return PRETTY.get(b, b)
KEEP_UP = {"CLA","CLE","EV3","EV6","EV9","EQA","EQB","EQC","EQE","EQS","ID3","ID4",
           "ID5","ID7","GT","AMG","EX30","EX40","EX90","MG","DS","SUV","GLA","GLB",
           "GLC","GLE","GLS","EQV","AWD","4MOTION","BZ4X","MX-30","C40","EC40"}
def model(s):
    out = []
    for w in str(s).split():
        u = w.upper()
        if u in KEEP_UP: out.append(u)
        elif u.startswith("IX") and u[2:].isdigit(): out.append("iX"+u[2:])
        elif u == "XDRIVE": out.append("xDrive")
        elif u.startswith("EDRIVE"): out.append("eDrive"+w[6:])
        elif u == "E-TECH": out.append("E-Tech")
        elif any(ch.isdigit() for ch in w): out.append(w)   # 250+, 85, 50, R5...
        else: out.append(w.capitalize())
    return " ".join(out)
MONTHS_EN = ["","January","February","March","April","May","June","July",
             "August","September","October","November","December"]

def load(path):
    d = json.load(open(path, encoding="utf-8"))
    D = d["dims"]
    return d, D, D["months"], d["rows"], D["segments"], D["operations"], \
        D["drivetrains"], D["brands"], D["models"]

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="data/registrations.json")
    ap.add_argument("--month", default=None, help="YYYY-MM (default: latest)")
    ap.add_argument("--out", default=".")
    a = ap.parse_args()

    d, D, M, R, S, O, DT, BR, MO = load(a.data)
    month = a.month or d["meta"].get("latest_month") or M[-1]
    if month and "-" not in month and len(month) == 6:
        month = month[:4] + "-" + month[4:]   # 202606 -> 2026-06
    if month not in M:
        raise SystemExit(f"{month} not in data (available {M[0]}..{M[-1]})")
    mi = M.index(month)
    yr, mo = month.split("-"); mo = int(mo)

    def car_new(r): return S[r[1]] == "car" and O[r[2]] == "new"
    # ---- month aggregates ----
    def month_counts(idx):
        tot = bev = 0; bb = Counter(); mm = Counter(); tesla = Counter()
        for r in R:
            if r[0] != idx or not car_new(r): continue
            tot += r[6]
            b = brand(BR[MO[r[4]][1]]); mdl = model(MO[r[4]][0])
            if DT[r[5]] == "BEV":
                bev += r[6]; bb[b] += r[6]; mm[f"{b} · {mdl}"] += r[6]
            if b == "Tesla": tesla[mdl] += r[6]
        return tot, bev, bb, mm, tesla
    tot, bev, bb, mm, tesla = month_counts(mi)
    share = bev / tot * 100 if tot else 0
    # prior month
    ptot = pbev = 0; pbb = Counter()
    if mi > 0:
        ptot, pbev, pbb, _, _ = month_counts(mi - 1)
    pshare = pbev / ptot * 100 if ptot else 0

    # ---- YTD (Jan..month of this year) ----
    ytd_tot = ytd_bev = 0; ytd_brand = Counter(); tesla_ytd = Counter()
    trend = []  # (monthLabel, share)
    for i, m in enumerate(M):
        if not m.startswith(yr): continue
        if int(m.split("-")[1]) > mo: continue
        t = b = 0
        for r in R:
            if r[0] != i or not car_new(r): continue
            t += r[6]
            bn = brand(BR[MO[r[4]][1]])
            if bn == "Tesla": tesla_ytd[model(MO[r[4]][0])] += r[6]
            if DT[r[5]] == "BEV":
                b += r[6]
                ytd_brand[bn] += r[6]   # YTD *BEV* leaders (matches the report format)
        ytd_tot += t; ytd_bev += b
        trend.append((MONTHS_EN[int(m.split("-")[1])][:3], b / t * 100 if t else 0))
    ytd_share = ytd_bev / ytd_tot * 100 if ytd_tot else 0

    # ---- long BEV-share history for the chart (all months) ----
    hist = []
    for i, m in enumerate(M):
        t = b = 0
        for r in R:
            if r[0] != i or not car_new(r): continue
            t += r[6]
            if DT[r[5]] == "BEV": b += r[6]
        hist.append((m, b / t * 100 if t else None))

    # ---- MoM narrative ----
    notes = []
    order = [b for b, _ in bb.most_common()]
    porder = [b for b, _ in pbb.most_common()]
    if share > pshare: notes.append(f"BEV share rose to {share:.1f}% (from {pshare:.1f}% last month).")
    elif share < pshare: notes.append(f"BEV share eased to {share:.1f}% (from {pshare:.1f}% last month).")
    if [s for _, s in trend] and abs(share - max(s for _, s in trend)) < 1e-9:
        notes.append(f"That's the highest BEV share so far in {yr}.")
    if len(order) >= 2:
        notes.append(f"{order[0]} led all BEV brands ({bb[order[0]]}), "
                     f"{'edging out' if bb[order[0]]-bb[order[1]]<=3 else 'ahead of'} "
                     f"{order[1]} ({bb[order[1]]}).")
    if mm:
        top_model, tm = mm.most_common(1)[0]
        notes.append(f"Best-selling BEV model: {top_model} ({tm}).")
    new_top10 = [b for b in order[:10] if b not in porder[:10]]
    if new_top10 and mi > 0:
        notes.append("New to the brand Top 10: " + ", ".join(new_top10) + ".")
    if porder and order:
        for b in order[:5]:
            if b in porder:
                jump = porder.index(b) - order.index(b)
                if jump >= 3:
                    notes.append(f"{b} climbed {jump} places to #{order.index(b)+1}.")
                    break

    ctx = dict(month=month, monthName=f"{MONTHS_EN[mo]} {yr}", tot=tot, bev=bev,
               share=share, pshare=pshare, bb=bb, mm=mm, tesla=tesla,
               ytd_tot=ytd_tot, ytd_bev=ytd_bev, ytd_share=ytd_share,
               ytd_brand=ytd_brand, tesla_ytd=tesla_ytd, trend=trend,
               hist=hist, notes=notes, yr=yr)
    os.makedirs(a.out, exist_ok=True)
    md_path = os.path.join(a.out, f"report_{month}.md")
    html_path = os.path.join(a.out, f"report_{month}.html")
    open(md_path, "w", encoding="utf-8").write(render_md(ctx))
    open(html_path, "w", encoding="utf-8").write(render_html(ctx))
    print(f"wrote {md_path}")
    print(f"wrote {html_path}")
    # console validation snapshot
    print(f"\n{ctx['monthName']}: {tot:,} new cars · {bev:,} BEV · {share:.1f}% share")


def render_md(c):
    L = []
    L.append(f"New BEV car registrations in Luxembourg \U0001F1F1\U0001F1FA, {c['monthName']}:\n")
    L.append(f"Total new car registrations: {c['tot']:,}")
    L.append(f"Total BEV registrations: {c['bev']:,}\n")
    trend_arrow = "an increase" if c["share"] >= c["pshare"] else "a decrease"
    L.append(f"In {c['monthName'].split()[0]}, BEVs accounted for {c['share']:.1f}% of total new "
             f"car registrations in Luxembourg, {trend_arrow} from last month's {c['pshare']:.1f}%.\n")
    L.append("Top 10 BEV by brand:")
    for b, n in c["bb"].most_common(10): L.append(f"{b} - {n}")
    L.append("\nTop 10 BEV by model:")
    for m, n in c["mm"].most_common(10): L.append(f"{m.split(' · ',1)[1]} - {n}")
    if c["tesla"]:
        L.append("\nTesla lineup:")
        for m, n in c["tesla"].most_common(): L.append(f"{m} - {n}")
        L.append(f"Total: {sum(c['tesla'].values())} units")
    L.append(f"\n\U0001F4CA {c['monthName'].split()[0]} highlights & YTD summary:\n")
    for note in c["notes"]: L.append(f"\u2022 {note}")
    tr = " \u2192 ".join(f"{mn} {s:.1f}%" for mn, s in c["trend"])
    L.append(f"\u2022 {c['yr']} monthly BEV share: {tr}")
    L.append(f"\u2022 YTD: {c['ytd_bev']:,} BEVs of {c['ytd_tot']:,} new registrations "
             f"({c['ytd_share']:.1f}% share)")
    lead = ", ".join(f"{b} ({n:,})" for b, n in c["ytd_brand"].most_common(6))
    L.append(f"\u2022 YTD BEV brand leaders: {lead}")
    if c["tesla_ytd"]:
        tl = ", ".join(f"{m}: {n}" for m, n in c["tesla_ytd"].most_common())
        L.append(f"\u2022 Tesla YTD: {sum(c['tesla_ytd'].values())} units ({tl})")
    return "\n".join(L) + "\n"


def _bars(items, unit_color, maxw=360):
    if not items: return ""
    mx = max(n for _, n in items) or 1
    out = []
    for label, n in items:
        w = max(2, n / mx * maxw)
        out.append(
            f'<div class="bar"><span class="bl">{label}</span>'
            f'<span class="bt"><span class="bf" style="width:{w:.0f}px;background:{unit_color}"></span>'
            f'<b>{n}</b></span></div>')
    return "".join(out)


def _spark(hist, w=920, h=180):
    pts = [(i, s) for i, (m, s) in enumerate(hist) if s is not None]
    if not pts: return ""
    n = len(hist); mx = max(s for _, s in pts) * 1.15 or 10
    PL, PR, PT, PB = 40, 12, 12, 24; iw = w - PL - PR; ih = h - PT - PB
    X = lambda i: PL + (i / (n - 1) * iw if n > 1 else iw / 2)
    Y = lambda s: PT + ih - s / mx * ih
    d = ""
    for k, (i, s) in enumerate(pts):
        d += ("M" if k == 0 else "L") + f"{X(i):.1f},{Y(s):.1f} "
    area = f"M{X(pts[0][0]):.1f},{PT+ih} " + "".join(f"L{X(i):.1f},{Y(s):.1f} " for i, s in pts) + f"L{X(pts[-1][0]):.1f},{PT+ih} Z"
    grid = "".join(
        f'<line x1="{PL}" y1="{PT+ih-g/4*ih:.0f}" x2="{w-PR}" y2="{PT+ih-g/4*ih:.0f}" stroke="#223" stroke-width="1"/>'
        f'<text x="{PL-6}" y="{PT+ih-g/4*ih+3:.0f}" text-anchor="end" fill="#8da0b0" font-size="10" font-family="monospace">{mx*g/4:.0f}%</text>'
        for g in range(5))
    yr_ticks = ""; last = None
    for i, (m, s) in enumerate(hist):
        y = m[:4]
        if y != last:
            last = y
            yr_ticks += f'<text x="{X(i):.0f}" y="{h-6}" text-anchor="middle" fill="#8da0b0" font-size="10" font-family="monospace">{y}</text>'
    return (f'<svg viewBox="0 0 {w} {h}" width="100%">{grid}'
            f'<path d="{area}" fill="#39d6c8" fill-opacity=".13"/>'
            f'<path d="{d}" fill="none" stroke="#39d6c8" stroke-width="2"/>{yr_ticks}</svg>')


def render_html(c):
    top_b = c["bb"].most_common(10)
    top_m = [(m.split(" · ", 1)[1], n) for m, n in c["mm"].most_common(10)]
    delta = c["share"] - c["pshare"]
    darrow = f'<span style="color:#7bd88f">\u25B2 {delta:+.1f} pts</span>' if delta >= 0 else f'<span style="color:#ff6b6b">\u25BC {delta:+.1f} pts</span>'
    notes = "".join(f"<li>{n}</li>" for n in c["notes"])
    lead = "".join(f"<tr><td>{b}</td><td>{n:,}</td></tr>" for b, n in c["ytd_brand"].most_common(8))
    tesla_rows = "".join(f"<tr><td>{m}</td><td>{n}</td></tr>" for m, n in c["tesla"].most_common())
    return f"""<!doctype html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Luxembourg BEV report · {c['monthName']}</title>
<style>
:root{{--bg:#0b0f14;--panel:#10171e;--line:#1e2831;--txt:#e8eef3;--mut:#8da0b0;--dim:#5d7080;--bev:#39d6c8;--amber:#ffb347}}
*{{box-sizing:border-box}} body{{margin:0;background:var(--bg);color:var(--txt);font-family:-apple-system,Segoe UI,Roboto,sans-serif;padding:26px;max-width:1000px;margin:auto}}
h1{{font-size:26px;margin:0 0 2px}} .sub{{color:var(--mut);font-family:monospace;font-size:13px;margin-bottom:20px}}
.grid{{display:grid;grid-template-columns:repeat(3,1fr);gap:12px;margin-bottom:18px}}
.kpi{{background:var(--panel);border:1px solid var(--line);border-radius:12px;padding:16px}}
.kpi .l{{color:var(--mut);font-family:monospace;font-size:11px;text-transform:uppercase;letter-spacing:.5px}}
.kpi .v{{font-size:30px;font-weight:800;margin-top:4px}} .kpi .s{{color:var(--mut);font-size:12px;margin-top:2px}}
.panel{{background:var(--panel);border:1px solid var(--line);border-radius:12px;padding:18px;margin-bottom:16px}}
.panel h3{{margin:0 0 12px;font-size:15px}}
.two{{display:grid;grid-template-columns:1fr 1fr;gap:16px}}
.bar{{display:flex;align-items:center;gap:10px;margin:6px 0;font-size:13px}}
.bl{{width:130px;color:var(--mut);text-align:right;flex:none;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}}
.bt{{display:flex;align-items:center;gap:8px;flex:1}} .bf{{height:16px;border-radius:4px;display:inline-block}}
.bt b{{font-family:monospace}}
table{{width:100%;border-collapse:collapse;font-size:13px}} td{{padding:5px 8px;border-bottom:1px solid var(--line)}}
td:last-child{{text-align:right;font-family:monospace;color:var(--mut)}}
ul{{margin:0;padding-left:18px;line-height:1.7}} li{{margin:3px 0}}
.foot{{color:var(--dim);font-size:11px;font-family:monospace;margin-top:20px}}
@media(max-width:720px){{.grid,.two{{grid-template-columns:1fr}} .bl{{width:96px}}}}
</style></head><body>
<h1>New BEV car registrations in Luxembourg \U0001F1F1\U0001F1FA</h1>
<div class="sub">{c['monthName']} &middot; from the open SNCA Parc Automobile dataset (CC0)</div>
<div class="grid">
  <div class="kpi"><div class="l">New car registrations</div><div class="v">{c['tot']:,}</div><div class="s">passenger cars, {c['monthName']}</div></div>
  <div class="kpi"><div class="l">BEV registrations</div><div class="v" style="color:var(--bev)">{c['bev']:,}</div><div class="s">{darrow} vs last month</div></div>
  <div class="kpi"><div class="l">BEV share</div><div class="v">{c['share']:.1f}%</div><div class="s">YTD {c['ytd_share']:.1f}% &middot; {c['ytd_bev']:,}/{c['ytd_tot']:,}</div></div>
</div>
<div class="panel"><h3>BEV adoption over time (share of new passenger cars)</h3>{_spark(c['hist'])}</div>
<div class="two">
  <div class="panel"><h3>Top 10 BEV by brand &middot; {c['monthName'].split()[0]}</h3>{_bars(top_b,'var(--bev)')}</div>
  <div class="panel"><h3>Top 10 BEV by model &middot; {c['monthName'].split()[0]}</h3>{_bars(top_m,'var(--amber)')}</div>
</div>
<div class="two">
  <div class="panel"><h3>Highlights</h3><ul>{notes}</ul></div>
  <div class="panel"><h3>YTD BEV brand leaders ({c['yr']})</h3><table>{lead}</table></div>
</div>
{"<div class='panel'><h3>Tesla lineup &middot; "+c['monthName'].split()[0]+"</h3><table>"+tesla_rows+"<tr><td><b>Total</b></td><td><b>"+str(sum(c['tesla'].values()))+"</b></td></tr></table></div>" if c['tesla'] else ""}
<div class="foot">Source: Parc Automobile du Luxembourg (SNCA) via data.public.lu, licence CC0 &middot; reconstructed from monthly fleet snapshots &middot; drivegreen-hub.github.io/Luxembourg-Car-Registration</div>
</body></html>"""


if __name__ == "__main__":
    main()
