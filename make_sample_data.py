#!/usr/bin/env python3
"""
make_sample_data.py
-------------------
Generates a REALISTIC but SYNTHETIC dataset shaped like Luxembourg new-vehicle
registrations, so the dashboard works out of the box before you run the real
pipeline (build_data.py). The output schema is IDENTICAL to what build_data.py
emits, so the dashboard needs no changes when you swap in real data.

Output: data/registrations.json   (compact, integer-coded)
"""
import json, math, random, os
from datetime import date

random.seed(42)

# ---- Time range: Jan 2022 .. Mar 2026 (last complete month) -----------------
months = []
y, m = 2022, 1
while (y, m) <= (2026, 3):
    months.append(f"{y:04d}-{m:02d}")
    m += 1
    if m == 13:
        m = 1; y += 1

segments    = ["car", "van", "bus"]
operations  = ["new", "import"]                       # brand-new vs used import
drivetrains = ["BEV", "PHEV", "HEV", "Petrol", "Diesel", "Other"]

# ---- Brand & model universe (Luxembourg-flavoured) --------------------------
# brand -> list of (model, body_segment, typical_drivetrain_weights)
W_EV    = {"BEV": .55, "PHEV": .15, "HEV": .10, "Petrol": .12, "Diesel": .06, "Other": .02}
W_PREM  = {"BEV": .30, "PHEV": .22, "HEV": .14, "Petrol": .20, "Diesel": .12, "Other": .02}
W_MASS  = {"BEV": .18, "PHEV": .10, "HEV": .24, "Petrol": .38, "Diesel": .08, "Other": .02}
W_VAN   = {"BEV": .20, "PHEV": .02, "HEV": .03, "Petrol": .15, "Diesel": .58, "Other": .02}
W_BUS   = {"BEV": .35, "PHEV": .01, "HEV": .04, "Petrol": .05, "Diesel": .53, "Other": .02}

BRANDS = {
    "BMW":        ([("Series 1","car"),("X1","car"),("X3","car"),("i4","car"),("iX1","car")], W_PREM, 1.00),
    "Mercedes":   ([("A-Class","car"),("GLC","car"),("EQA","car"),("C-Class","car"),("Vito","van")], W_PREM, 0.98),
    "Audi":       ([("A3","car"),("Q4 e-tron","car"),("Q3","car"),("A4","car")], W_PREM, 0.92),
    "Volkswagen": ([("Golf","car"),("Tiguan","car"),("ID.4","car"),("T-Roc","car"),("Transporter","van")], W_MASS, 1.05),
    "Tesla":      ([("Model 3","car"),("Model Y","car")], W_EV, 0.80),
    "Renault":    ([("Clio","car"),("Captur","car"),("Megane E-Tech","car"),("Master","van")], W_MASS, 0.78),
    "Peugeot":    ([("208","car"),("2008","car"),("3008","car"),("Partner","van")], W_MASS, 0.74),
    "Toyota":     ([("Yaris","car"),("Corolla","car"),("C-HR","car"),("RAV4","car")], W_MASS, 0.70),
    "Skoda":      ([("Octavia","car"),("Enyaq","car"),("Kodiaq","car")], W_MASS, 0.66),
    "Volvo":      ([("XC40","car"),("EX30","car"),("XC60","car")], W_PREM, 0.55),
    "Cupra":      ([("Formentor","car"),("Born","car")], W_PREM, 0.50),
    "Dacia":      ([("Sandero","car"),("Duster","car"),("Spring","car")], W_MASS, 0.48),
    "Hyundai":    ([("Tucson","car"),("Kona","car"),("Ioniq 5","car")], W_MASS, 0.46),
    "Kia":        ([("Sportage","car"),("Niro","car"),("EV6","car")], W_MASS, 0.44),
    "Ford":       ([("Puma","car"),("Kuga","car"),("Transit","van")], W_MASS, 0.42),
    "Citroen":    ([("C3","car"),("C4","car"),("Berlingo","van")], W_MASS, 0.36),
    "Opel":       ([("Corsa","car"),("Mokka","car"),("Vivaro","van")], W_MASS, 0.34),
    "Fiat":       ([("500","car"),("Panda","car"),("Ducato","van")], W_MASS, 0.30),
    "MAN":        ([("Lion's City","bus"),("TGE","van")], W_BUS, 0.10),
    "Mercedes-Bus":([("Citaro","bus"),("Tourismo","bus")], W_BUS, 0.06),
}

def month_index(ym):
    return months.index(ym)

def seasonal(ym):
    """Luxembourg 'Autofestival' (late Jan–Feb) lifts Feb/Mar registrations."""
    mm = int(ym[5:7])
    base = 1.0
    if mm in (2, 3): base = 1.35
    elif mm in (1,): base = 0.85
    elif mm in (7, 8): base = 0.80
    elif mm in (12,): base = 0.78
    return base

def bev_trend(ym):
    """Gradually shift drivetrain mix toward BEV over time (2022->2026)."""
    t = month_index(ym) / max(1, len(months) - 1)   # 0..1
    return t

def mix_for(weights, ym):
    """Return a drivetrain probability dict, nudged toward BEV over time."""
    t = bev_trend(ym)
    w = dict(weights)
    boost = 1.0 + 1.1 * t                # BEV grows
    decay = 1.0 - 0.45 * t               # diesel/petrol shrink
    w["BEV"]    *= boost
    w["PHEV"]   *= (1.0 + 0.2 * t)
    w["Diesel"] *= decay
    w["Petrol"] *= (1.0 - 0.30 * t)
    s = sum(w.values())
    return {k: v / s for k, v in w.items()}

def co2_avg(dt, ym):
    """Realistic WLTP CO2 (g/km) per drivetrain, gently declining over time."""
    t = bev_trend(ym)                       # 0..1 across the window
    base = {"BEV": 0, "PHEV": 48, "HEV": 112,
            "Petrol": 142, "Diesel": 150, "Other": 122}[dt]
    if dt == "BEV":
        return 0.0
    decline = 1.0 - 0.12 * t                # fleets get a bit cleaner
    return base * decline * random.uniform(0.94, 1.06)


def split_counts(total, probs):
    """Multinomial-ish split of an integer total across drivetrains."""
    keys = list(probs.keys())
    raw = {k: total * probs[k] for k in keys}
    out = {k: int(math.floor(raw[k])) for k in keys}
    rem = total - sum(out.values())
    # distribute remainder by fractional part
    fracs = sorted(keys, key=lambda k: raw[k] - out[k], reverse=True)
    for i in range(rem):
        out[fracs[i % len(fracs)]] += 1
    return out

# ---- Build flat rows --------------------------------------------------------
rows = []  # [monthIdx, segIdx, opIdx, brandIdx, modelIdx, dtIdx, count, co2sum, co2n]
brand_list = list(BRANDS.keys())
# global model registry -> stable indices
model_registry = []          # list of [modelName, brandIdx]
model_lookup = {}            # (brandIdx, modelName) -> modelIdx

def model_id(brand_idx, name):
    key = (brand_idx, name)
    if key not in model_lookup:
        model_lookup[key] = len(model_registry)
        model_registry.append([name, brand_idx])
    return model_lookup[key]

for ym in months:
    seas = seasonal(ym)
    for b_idx, brand in enumerate(brand_list):
        model_defs, base_weights, brand_strength = BRANDS[brand]
        for (model_name, body_seg) in model_defs:
            seg_idx = segments.index(body_seg)
            mdl_idx = model_id(b_idx, model_name)
            # base monthly volume for this model
            if body_seg == "car":
                base = 38 * brand_strength
            elif body_seg == "van":
                base = 14 * brand_strength
            else:
                base = 3 * brand_strength
            for op in operations:
                op_idx = operations.index(op)
                # imports are a smaller, noisier stream (mostly premium/used)
                op_factor = 1.0 if op == "new" else 0.22
                vol = base * seas * op_factor * random.uniform(0.7, 1.3)
                total = max(0, int(round(vol)))
                if total == 0:
                    continue
                weights = (W_VAN if body_seg == "van" else
                           W_BUS if body_seg == "bus" else base_weights)
                probs = mix_for(weights, ym)
                # imports skew slightly less electric
                if op == "import":
                    probs = dict(probs)
                    probs["BEV"] *= 0.6; probs["Diesel"] *= 1.4
                    s = sum(probs.values()); probs = {k: v/s for k, v in probs.items()}
                counts = split_counts(total, probs)
                for dt, n in counts.items():
                    if n <= 0:
                        continue
                    co2sum = int(round(n * co2_avg(dt, ym)))
                    # co2n = vehicles with a known CO2 value (all, in the sample;
                    # BEVs count as a known 0). Real data may have co2n < count.
                    rows.append([month_index(ym), seg_idx, op_idx, b_idx,
                                 mdl_idx, drivetrains.index(dt), n, co2sum, n])

out = {
    "meta": {
        "generated": date.today().isoformat(),
        "source": "SYNTHETIC SAMPLE DATA (not real). Replace via build_data.py.",
        "source_snapshot": "sample",
        "latest_month": months[-1],
        "note": "Brand-new = first LU registration equals first-ever registration. "
                "Import = vehicle previously registered abroad. Historical months "
                "reconstructed from one fleet snapshot are subject to survivorship "
                "bias the further back you go.",
    },
    "dims": {
        "months": months,
        "segments": segments,
        "operations": operations,
        "drivetrains": drivetrains,
        "brands": brand_list,
        "models": model_registry,     # [ [name, brandIdx], ... ]
    },
    "rows": rows,
}

os.makedirs("data", exist_ok=True)
with open("data/registrations.json", "w", encoding="utf-8") as f:
    json.dump(out, f, separators=(",", ":"), ensure_ascii=False)

print(f"Wrote data/registrations.json")
print(f"  months : {len(months)} ({months[0]} .. {months[-1]})")
print(f"  brands : {len(brand_list)}  models: {len(model_registry)}")
print(f"  rows   : {len(rows)}")
print(f"  size   : {os.path.getsize('data/registrations.json')/1024:.0f} KB")
