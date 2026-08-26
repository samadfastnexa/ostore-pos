"""Fill in prices for the imported Murshid catalogue.

The source sheets carry no pricing at all, so these are ILLUSTRATIVE figures
built from 2025 Pakistani hardware-market ballparks: a baseline per category,
adjusted for the material and the size parsed out of each product name, plus a
small deterministic spread so items within a category are not all identical.

Deterministic on purpose (crc32 of the name, not random) so re-running produces
exactly the same numbers instead of churning the catalogue.

Every product gets the full ladder, which is what the till's price-range
feature needs: cost < minimum selling < sales price < MRP.
"""
import re
from zlib import crc32

# Retail (sales) baseline in PKR per sub-category.
BASE = {
    "Electrical / Batteries": 40,
    "Electrical / Bulbs & Lights": 350,
    "Electrical / Capacitors": 260,
    "Electrical / Conduit & Utility Pipe": 130,
    "Electrical / Holders & Adapters": 95,
    "Electrical / Switches & Sockets": 190,
    "Electrical / Wires & Cables": 90,
    "Gas / Gas Pipes & Fittings": 380,
    "Gas / Gas Valves & Keys": 460,
    "Hardware & Tools / Abrasives": 130,
    "Hardware & Tools / Adhesives & Sealants": 260,
    "Hardware & Tools / Cutting Discs & Blades": 190,
    "Hardware & Tools / Fasteners": 25,
    "Hardware & Tools / Hand Tools": 620,
    "Hardware & Tools / Locks": 950,
    "Hardware & Tools / Tapes & Measures": 210,
    "Plumbing / GI Fittings": 230,
    "Plumbing / Hoses & Connections": 360,
    "Plumbing / Valves": 720,
    "Plumbing / Water Lines & Pipes": 460,
    "Sanitary / Bathroom Accessories": 560,
    "Sanitary / Bathroom Fittings": 820,
    "Sanitary / Sanitary Ware": 6500,
    "Sanitary / Showers & Hoses": 900,
    "Sanitary / Taps & Valves": 1250,
    "Sanitary / UPVC Pipes & Fittings": 310,
}
DEFAULT_BASE = 250

# Material and grade cues that genuinely move price on a hardware shelf.
KEYWORDS = [
    ("brass", 1.9), ("chrome", 1.45), ("stainless", 1.6), (" ss", 1.35),
    ("steill", 1.3), ("steel", 1.3), ("copper", 1.7),
    ("pvc", 0.62), ("plastic", 0.55), ("nylon", 0.7),
    ("complete", 1.5), ("set", 1.35), ("heavy", 1.3), ("master", 1.2),
    ("quality 1", 1.35), ("quality 2", 1.2), ("quality 3", 1.05),
    ("quality 4", 0.92), ("quality 8", 0.75),
    ("large", 1.3), ("medium", 1.0), ("small", 0.8), ("mini", 0.7),
]

FRACTION = re.compile(r"(\d+)\s*-\s*(\d+)\s*/\s*(\d+)|(\d+)\s*/\s*(\d+)|(\d+(?:\.\d+)?)")


def size_factor(name):
    """Scale by the physical size in the name: a 4 inch valve is not a 1/2 inch one."""
    low = name.lower()
    unit = None
    for u in ("inch", '"', " mm", " w", " watt", " amp", " a "):
        if u in low:
            unit = u.strip()
            break
    if not unit:
        return 1.0
    m = FRACTION.search(low)
    if not m:
        return 1.0
    if m.group(1):                                   # 1-1/2
        val = int(m.group(1)) + int(m.group(2)) / int(m.group(3))
    elif m.group(4):                                 # 1/2
        val = int(m.group(4)) / int(m.group(5))
    else:
        val = float(m.group(6))
    if unit in ("inch", '"'):
        f = 0.55 + 0.45 * val
    elif unit == "mm":
        f = 0.6 + val / 45.0
    elif unit in ("w", "watt"):
        f = 0.5 + val / 24.0
    else:                                            # amps
        f = 0.7 + val / 30.0
    return max(0.4, min(f, 4.5))


def spread(name):
    """Stable +/-12% so a category is not a wall of identical prices."""
    return 0.88 + (crc32(name.encode("utf8")) % 25) / 100.0


def tidy(v):
    if v < 100:
        return round(v / 5) * 5 or 5
    if v < 1000:
        return round(v / 10) * 10
    return round(v / 50) * 50


IMD = env["ir.model.data"].sudo()
ids = IMD.search([("module", "=", "__murshid__"), ("model", "=", "product.template")]).mapped("res_id")
prods = env["product.template"].sudo().browse(ids)

ok = fail = 0
for p in prods:
    try:
        base = BASE.get(p.categ_id.complete_name, DEFAULT_BASE)
        price = base * size_factor(p.name) * spread(p.name)
        low = p.name.lower()
        for kw, mult in KEYWORDS:
            if kw in low:
                price *= mult
        sales = tidy(price)
        vals = {
            "standard_price": tidy(sales * 0.72),   # what it cost to buy in
            "minimum_selling_price": tidy(sales * 0.92),  # floor before approval
            "list_price": sales,
            "mrp": tidy(sales * 1.15),              # printed ceiling
        }
        # The ladder must stay strictly ordered after rounding, or the till
        # would ask for a manager override on an ordinary sale.
        if vals["minimum_selling_price"] >= vals["list_price"]:
            vals["minimum_selling_price"] = tidy(vals["list_price"] * 0.9) or vals["list_price"]
        if vals["mrp"] <= vals["list_price"]:
            vals["mrp"] = vals["list_price"] + tidy(vals["list_price"] * 0.1)
        p.write(vals)
        ok += 1
        if ok % 50 == 0:
            env.cr.commit()
    except Exception as e:
        env.cr.rollback()
        fail += 1
        print(f"  FAIL '{p.name}': {str(e)[:110]}")
env.cr.commit()
print(f"priced={ok} failed={fail}")
