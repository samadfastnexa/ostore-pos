"""Import the Murshid store catalogue from import-data/murshid-store/*.xlsx.

WHICH BRANCH DOES A PRODUCT GO TO?

Products are owned by one branch each, so every row has to name its branch. The
products sheet may carry a "Branch" column:

    Branch = "Cash & Carry"        -> created for that branch only
    Branch = "johar town Branch1"  -> created for that branch only
    Branch = "ALL", "BOTH" or blank -> created SEPARATELY for every branch,
                                       one independent record per branch

DEFAULT_BRANCHES below decides what a blank cell means; leave it as None to mean
"every branch". A branch name that matches no company stops the import for that
row rather than guessing, so a typo cannot silently load stock into the wrong
shop.

Till sections (2_till_sections) and brands (3b_brands) accept a Branch column of
their own, added by pos_retail since Odoo ships neither model with a company.
There, a BLANK cell means one shared record used by every branch -- not a copy
per branch -- because a section shared by both shops should not split the
products beneath it.

Product categories (1_categories) take a Branch column on the same terms: blank
means one shared category used by every branch. Scoping one costs nothing on the
accounting side, because a category's account fields are company-dependent -- a
single category already holds a separate income, expense and stock-valuation
account per branch, so the column only decides who SEES the category.

Idempotent: each product is registered as "<External ID>__c<company id>", so a
re-run updates that branch's record instead of creating another.

Run with:
    odoo-bin shell -c odoo.conf -d <db> --no-http < this_file
"""
import openpyxl

BASE = "import-data/murshid-store"
MODULE = "__murshid__"
IMD = env["ir.model.data"].sudo()

# What a blank/ALL Branch cell means. None = every branch in the database.
DEFAULT_BRANCHES = None

ALL_BRANCHES = env["res.company"].sudo().search([], order="id")
BRANCH_BY_NAME = {c.name.strip().lower(): c for c in ALL_BRANCHES}


def resolve_branches(raw):
    """Turn a Branch cell into the companies the row should be created for."""
    value = (raw or "").strip()
    if not value or value.lower() in ("all", "both", "*"):
        return DEFAULT_BRANCHES or ALL_BRANCHES
    found = env["res.company"].sudo().browse()
    for part in value.replace(";", ",").split(","):
        key = part.strip().lower()
        if not key:
            continue
        branch = BRANCH_BY_NAME.get(key)
        if not branch:
            raise ValueError(
                f"unknown branch {part.strip()!r} - known branches: "
                + ", ".join(c.name for c in ALL_BRANCHES)
            )
        found |= branch
    return found


def sheet(path):
    ws = openpyxl.load_workbook(f"{BASE}/{path}", data_only=True).worksheets[0]
    data = list(ws.iter_rows(values_only=True))
    hdr = [str(h).strip() if h else "" for h in data[0]]
    out = []
    for r in data[1:]:
        if not any(c is not None and str(c).strip() for c in r):
            continue
        out.append({k: (str(v).strip() if v is not None else "") for k, v in zip(hdr, r)})
    return out


def existing(extid):
    return env.ref(f"{MODULE}.{extid}", raise_if_not_found=False)


def remember(extid, record):
    if not extid or IMD.search_count([("module", "=", MODULE), ("name", "=", extid)]):
        return
    IMD.create({
        "module": MODULE, "name": extid,
        "model": record._name, "res_id": record.id, "noupdate": True,
    })


def upsert(model, extid, vals, match=None):
    """Return the record for extid, creating or updating as needed."""
    rec = existing(extid)
    if not rec and match:
        rec = env[model].sudo().search(match, limit=1)
    if rec:
        rec.sudo().write(vals)
    else:
        rec = env[model].sudo().create(vals)
    remember(extid, rec)
    return rec


stats = {}

# ---------------------------------------------------------------- categories
cats = sheet("1_categories.xlsx")
by_name = {}
by_path = {}
# Roots first so a child never looks for a parent that does not exist yet.
for pas in (0, 1):
    for row in cats:
        name, parent = row["Name"], row.get("Parent Category", "")
        if bool(parent) != bool(pas):
            continue
        try:
            parent_id = False
            if parent:
                if parent not in by_name:
                    print(f"  SKIP category '{name}': parent '{parent}' not found")
                    continue
                parent_id = by_name[parent].id
            # parent_id is always written, including False for a root: a plain
            # name match can land on a same-named category sitting somewhere
            # else in the tree, and without this the sheet's roots get quietly
            # adopted by it.
            branch_cell = (row.get("Branch") or "").strip()
            branch = resolve_branches(branch_cell)[0] if branch_cell else None
            vals = {"name": name, "parent_id": parent_id,
                    "company_id": branch.id if branch else False}
            # Match on name AND parent. Category names are only unique within a
            # parent -- "Sanitary" can legitimately exist in several branches --
            # so matching on name alone merges unrelated categories.
            extid = row.get("External ID", "")
            suffix = f"__c{branch.id}" if branch else ""
            rec = upsert("product.category", f"{extid}{suffix}" if extid else "", vals,
                         match=[("name", "=", name), ("parent_id", "=", parent_id),
                                ("company_id", "=", branch.id if branch else False)])
            by_name[name] = rec
            # Keyed the way the PRODUCTS sheet writes them ("Parent / Child"),
            # not by Odoo's complete_name: the two differ as soon as a root sits
            # under another category, and then nothing resolves.
            by_path[f"{parent} / {name}" if parent else name] = rec
            env.cr.commit()
        except Exception as e:
            env.cr.rollback()
            print(f"  FAIL category '{name}': {e}")
stats["categories"] = len(by_name)

# ------------------------------------------------------------- till sections
# Till sections take a Branch column too. Blank means every branch, which is
# how a section shared by both shops is expressed. Naming ONE branch creates the
# section for that branch only, and the other shop never sees the chip.
till = {}
for row in sheet("2_till_sections.UPDATED.xlsx"):
    name = row["Category Name"]
    try:
        branch_cell = (row.get("Branch") or "").strip()
        # A blank cell stays company-less rather than being duplicated per
        # branch: unlike a product, one section record can legitimately serve
        # every shop, and duplicating it would split the products beneath it.
        targets = resolve_branches(branch_cell) if branch_cell else [None]
        for branch in targets:
            vals = {"name": name, "sequence": int(row.get("Sequence") or 0),
                    "company_id": branch.id if branch else False}
            extid = row.get("External ID", "")
            suffix = f"__c{branch.id}" if branch else ""
            rec = upsert("pos.category", f"{extid}{suffix}" if extid else "", vals,
                         match=[("name", "=", name),
                                ("company_id", "=", branch.id if branch else False)])
            till[name] = rec
        env.cr.commit()
    except Exception as e:
        env.cr.rollback()
        print(f"  FAIL till section '{name}': {e}")
stats["till_sections"] = len(till)

# -------------------------------------------------------------------- brands
# Brands behave like till sections: blank Branch = stocked by every shop.
brands = {}
for row in sheet("3b_brands.xlsx"):
    name = row["Brand"]
    try:
        branch_cell = (row.get("Branch") or "").strip()
        targets = resolve_branches(branch_cell) if branch_cell else [None]
        for branch in targets:
            extid = row.get("External ID", "")
            suffix = f"__c{branch.id}" if branch else ""
            brands[name] = upsert(
                "product.brand", f"{extid}{suffix}" if extid else "",
                {"name": name, "company_id": branch.id if branch else False},
                match=[("name", "=", name),
                       ("company_id", "=", branch.id if branch else False)])
        env.cr.commit()
    except Exception as e:
        env.cr.rollback()
        print(f"  FAIL brand '{name}': {e}")
stats["brands"] = len(brands)

# ---------------------------------------------------------------------- tags
tags = {}
for row in sheet("3c_quality_tags.xlsx"):
    name = row["Name"]
    try:
        tags[name] = upsert("product.tag", row.get("External ID", ""),
                            {"name": name}, match=[("name", "=", name)])
        env.cr.commit()
    except Exception as e:
        env.cr.rollback()
        print(f"  FAIL tag '{name}': {e}")
stats["tags"] = len(tags)

# ------------------------------------------------------------------ products
uoms = {}
for u in ("Units", "m", "ft", "Set"):
    found = env["uom.uom"].sudo().search([("name", "=", u)], limit=1)
    if found:
        uoms[u] = found

def truthy(v):
    return str(v).strip().upper() in ("TRUE", "1", "YES", "X")

def number(v):
    try:
        return float(str(v).replace(",", "")) if str(v).strip() else 0.0
    except ValueError:
        return 0.0

ok = fail = skipped = 0
per_branch = {}
for i, row in enumerate(sheet("4_products.UPDATED-Roman-name-fix.xlsx"), start=1):
    name = row["Name"]
    extid = row.get("External ID", "")
    try:
        branches = resolve_branches(row.get("Branch"))
        if not branches:
            skipped += 1
            print(f"  SKIP '{name}': no branch resolved")
            continue

        base = {
            "name": name,
            "type": "consu",
            "is_storable": truthy(row.get("Track Inventory")),
            "available_in_pos": truthy(row.get("Available in POS")),
            "sale_ok": truthy(row.get("Sales")),
            "purchase_ok": truthy(row.get("Purchase")),
            "list_price": number(row.get("Sales Price")),
            "standard_price": number(row.get("Cost")),
        }
        if row.get("Minimum Selling Price"):
            base["minimum_selling_price"] = number(row["Minimum Selling Price"])
        if row.get("Maximum Retail Price (MRP)"):
            base["mrp"] = number(row["Maximum Retail Price (MRP)"])
        # Categories, brands and tags carry no company in Odoo, so the same
        # records are referenced by every branch's copy.
        cat = by_path.get(row.get("Product Category", ""))
        if cat:
            base["categ_id"] = cat.id
        pos_cat = till.get(row.get("Point of Sale Category", ""))
        if pos_cat:
            base["pos_categ_ids"] = [(6, 0, [pos_cat.id])]
        brand = brands.get(row.get("Brand", ""))
        if brand:
            base["brand_id"] = brand.id
        uom = uoms.get(row.get("Unit", ""))
        if uom:
            base["uom_id"] = uom.id
        tag_names = [tg.strip() for tg in (row.get("Tags") or "").split(",") if tg.strip()]
        tag_ids = [tags[tg].id for tg in tag_names if tg in tags]
        if tag_ids:
            base["product_tag_ids"] = [(6, 0, tag_ids)]

        for branch in branches:
            vals = dict(base, company_id=branch.id)
            # One xmlid per branch, so a re-run updates that branch's own record
            # rather than dragging a product from one shop to another.
            branch_extid = f"{extid}__c{branch.id}" if extid else ""
            # Fall back to name+company for rows imported before branches
            # existed, so the first branch-aware run adopts them instead of
            # creating a second copy alongside.
            upsert("product.template", branch_extid, vals,
                   match=[("name", "=", name), ("company_id", "=", branch.id)])
            per_branch[branch.name] = per_branch.get(branch.name, 0) + 1

        ok += 1
        if i % 25 == 0:
            env.cr.commit()
            print(f"  ... {i} rows")
    except Exception as e:
        env.cr.rollback()
        fail += 1
        print(f"  FAIL product '{name}': {str(e)[:130]}")
env.cr.commit()
stats["rows_skipped_no_branch"] = skipped
for bname, n in sorted(per_branch.items()):
    stats[f"products in '{bname}'"] = n
stats["products_ok"] = ok
stats["products_failed"] = fail

print("\n=== IMPORT SUMMARY ===")
for k, v in stats.items():
    print(f"  {k}: {v}")
