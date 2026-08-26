"""Apply prices from 6_prices_TO_FILL.xlsx back onto the imported products.

Matched by External ID, so renaming a product in the sheet cannot mis-target a
row. Blank cells are left alone rather than zeroed, so the sheet can be filled
in over several passes. Idempotent.
"""
import openpyxl

SRC = "import-data/murshid-store/6_prices_TO_FILL.xlsx"
FIELDS = {
    "Cost": "standard_price",
    "Minimum Selling Price": "minimum_selling_price",
    "Sales Price": "list_price",
    "Maximum Retail Price (MRP)": "mrp",
}

ws = openpyxl.load_workbook(SRC, data_only=True).worksheets[0]
data = list(ws.iter_rows(values_only=True))
hdr = [str(h).strip() if h else "" for h in data[0]]

def number(v):
    if v is None or str(v).strip() == "":
        return None
    try:
        return float(str(v).replace(",", "").replace("Rs.", "").strip())
    except ValueError:
        return None

updated = skipped = missing = bad = 0
for raw in data[1:]:
    row = dict(zip(hdr, raw))
    extid = (row.get("External ID") or "").strip()
    if not extid and not (row.get("Name") or "").strip():
        continue
    # Match inside the row's own branch. Product names repeat across branches
    # by design now, so a name-only match would price whichever copy came first
    # and silently leave the other shop untouched.
    branch_name = (row.get("Branch") or "").strip()
    branch = env["res.company"].sudo().search([("name", "=", branch_name)], limit=1)
    rec = env.ref(f"__murshid__.{extid}", raise_if_not_found=False)
    if branch:
        rec = env["product.template"].sudo().search(
            [("name", "=", (row.get("Name") or "").strip()), ("company_id", "=", branch.id)],
            limit=1) or rec
    if not rec:
        missing += 1
        continue
    vals = {}
    for col, field in FIELDS.items():
        n = number(row.get(col))
        if n is not None:
            vals[field] = n
    if not vals:
        skipped += 1
        continue
    # A selling floor above the ceiling would make every sale need an override.
    lo, hi = vals.get("minimum_selling_price"), vals.get("mrp")
    if lo and hi and lo > hi:
        print(f"  SKIP '{row.get('Name')}': minimum {lo} is above MRP {hi}")
        bad += 1
        continue
    try:
        rec.sudo().write(vals)
        env.cr.commit()
        updated += 1
    except Exception as e:
        env.cr.rollback()
        bad += 1
        print(f"  FAIL '{row.get('Name')}': {str(e)[:110]}")

print(f"\nupdated={updated} untouched(blank)={skipped} unknown_extid={missing} rejected={bad}")
