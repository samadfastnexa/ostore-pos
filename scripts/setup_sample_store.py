# -*- coding: utf-8 -*-
"""
Idempotent sample-store setup for the pos_retail MVP.

Run in the Odoo shell (commits at the end):
    venv\\Scripts\\python.exe odoo\\odoo-bin shell -c odoo.conf -d learningO --no-http < custom_addons/pos_retail/scripts/setup_sample_store.py

Configures a realistic retail store on top of the standard apps so every
"config-only" MVP feature is demonstrable: categories, POS categories, tags,
brands, products (barcode/SKU/cost/price/uom/variants/expiry), initial stock,
reorder rules, vendors + supplier info, customers with membership, promotions
(product/order/category/BOGO) and JazzCash/EasyPaisa payment methods.

Safe to re-run: everything is looked up by a natural key before creating.
"""
from datetime import date, timedelta

# ---------------------------------------------------------------------------
# SAFETY GUARD -- demo data must never land in a real shop's database.
# These scripts create fake products, customers, expenses and (in part 3)
# POSTED journal entries. A posted entry cannot be cleanly deleted from a live
# ledger, so refusing up front is the only real protection.
# ---------------------------------------------------------------------------
def _refuse_if_live(env):
    import os
    if os.environ.get("POS_RETAIL_SEED_OK") == "yes":
        print("  [WARN   ] live-database guard bypassed via POS_RETAIL_SEED_OK")
        return
    signals = []
    posted = env["account.move"].search_count(
        [("move_type", "in", ("out_invoice", "out_refund")), ("state", "=", "posted")])
    if posted:
        signals.append(f"{posted} posted customer invoice(s)")
    closed = env["pos.session"].search_count([("state", "=", "closed")])
    if closed:
        signals.append(f"{closed} closed POS session(s)")
    if signals:
        raise RuntimeError(
            "REFUSING TO SEED: this database shows signs of real trading ("
            + "; ".join(signals) + "). Demo data cannot be cleanly removed once "
            "it is in a live ledger. Run this on a scratch database instead, or "
            "set the environment variable POS_RETAIL_SEED_OK=yes to override "
            "deliberately."
        )


_refuse_if_live(env)

report = {"created": [], "skipped": [], "failed": []}


def _log(kind, label):
    report[kind].append(label)
    print(f"  [{kind.upper():7}] {label}")


def gc(model, domain, vals, label):
    """get-or-create by domain; returns the record."""
    rec = env[model].search(domain, limit=1)
    if rec:
        _log("skipped", f"{model}: {label}")
        return rec
    rec = env[model].create(vals)
    _log("created", f"{model}: {label}")
    return rec


company = env.company
warehouse = env["stock.warehouse"].search([("company_id", "=", company.id)], limit=1)
stock_loc = warehouse.lot_stock_id
uom_unit = env.ref("uom.product_uom_unit")
uom_kg = env.ref("uom.product_uom_kgm")
uom_litre = env.ref("uom.product_uom_litre")
categ_all = env.ref("product.product_category_goods")
term_30 = env.ref("account.account_payment_term_30days")
term_imm = env.ref("account.account_payment_term_immediate")

print(f"\nSetting up sample store for company '{company.name}' (warehouse {warehouse.code}) ...\n")

# ----------------------------------------------------------------------------
# 1. Brands
# ----------------------------------------------------------------------------
print("Brands:")
brands = {}
for name in ["Nestle", "Coca-Cola", "Pepsi", "Olpers", "National"]:
    brands[name] = gc("product.brand", [("name", "=", name)], {"name": name}, name)

# ----------------------------------------------------------------------------
# 2. Product & POS categories
# ----------------------------------------------------------------------------
print("Product categories:")
pcateg = {}
for name in ["Beverages", "Snacks", "Dairy", "Grocery", "Apparel"]:
    pcateg[name] = gc("product.category", [("name", "=", name)],
                      {"name": name, "parent_id": categ_all.id}, name)

print("POS categories:")
poscateg = {}
for name in ["Beverages", "Snacks", "Dairy", "Grocery", "Apparel"]:
    poscateg[name] = gc("pos.category", [("name", "=", name)], {"name": name}, name)

# ----------------------------------------------------------------------------
# 3. Product tags
# ----------------------------------------------------------------------------
print("Product tags:")
tags = {}
for name, color in [("Imported", 1), ("Halal", 10), ("Local", 4)]:
    tags[name] = gc("product.tag", [("name", "=", name)], {"name": name, "color": color}, name)

# ----------------------------------------------------------------------------
# 4. Products (simple, storable, available in POS)
# ----------------------------------------------------------------------------
print("Products:")


def make_product(code, name, price, cost, categ, poscat, brand=None,
                 tag_names=(), uom=None, barcode=None, stock_qty=0.0,
                 reorder=None):
    uom = uom or uom_unit
    tmpl = env["product.template"].search([("default_code", "=", code)], limit=1)
    if tmpl:
        _log("skipped", f"product: {name}")
    else:
        vals = {
            "name": name,
            "default_code": code,
            "barcode": barcode,
            "type": "consu",
            "is_storable": True,
            "available_in_pos": True,
            "list_price": price,
            "standard_price": cost,
            "categ_id": pcateg[categ].id,
            "pos_categ_ids": [(6, 0, [poscateg[poscat].id])],
            "uom_id": uom.id,
            "product_tag_ids": [(6, 0, [tags[t].id for t in tag_names])],
        }
        if brand:
            vals["brand_id"] = brands[brand].id
        tmpl = env["product.template"].create(vals)
        _log("created", f"product: {name}")
    # initial stock (non-tracked variants only)
    variant = tmpl.product_variant_id
    if stock_qty and tmpl.tracking == "none" and variant:
        on_hand = env["stock.quant"]._get_available_quantity(variant, stock_loc)
        if on_hand < stock_qty:
            env["stock.quant"]._update_available_quantity(variant, stock_loc, stock_qty - on_hand)
            _log("created", f"stock: {name} +{stock_qty - on_hand}")
    # reorder rule
    if reorder:
        mn, mx = reorder
        op = env["stock.warehouse.orderpoint"].search(
            [("product_id", "=", variant.id), ("location_id", "=", stock_loc.id)], limit=1)
        if not op:
            env["stock.warehouse.orderpoint"].create({
                "product_id": variant.id,
                "warehouse_id": warehouse.id,
                "location_id": stock_loc.id,
                "product_min_qty": mn,
                "product_max_qty": mx,
            })
            _log("created", f"reorder rule: {name} ({mn}/{mx})")
    return tmpl


try:
    coke = make_product("COKE500", "Coca-Cola 500ml", 80, 55, "Beverages", "Beverages",
                        brand="Coca-Cola", tag_names=["Imported", "Halal"], barcode="5449000000996",
                        stock_qty=120, reorder=(20, 150))
    pepsi = make_product("PEPSI500", "Pepsi 500ml", 75, 52, "Beverages", "Beverages",
                        brand="Pepsi", tag_names=["Imported", "Halal"], barcode="5410000110015",
                        stock_qty=90, reorder=(20, 120))
    water = make_product("WATER15", "Nestle Water 1.5L", 60, 40, "Beverages", "Beverages",
                        brand="Nestle", tag_names=["Halal"], barcode="6001240000015",
                        stock_qty=80)
    lays = make_product("LAYS-CL", "Lays Classic Chips", 50, 33, "Snacks", "Snacks",
                        tag_names=["Local", "Halal"], barcode="8964000110022", stock_qty=200,
                        reorder=(30, 250))
    masala = make_product("NAT-MASALA", "National Chicken Masala", 120, 90, "Grocery", "Grocery",
                        brand="National", tag_names=["Local", "Halal"], barcode="8964000220033",
                        stock_qty=60)
    sugar = make_product("SUGAR-KG", "Refined Sugar (per Kg)", 140, 120, "Grocery", "Grocery",
                        tag_names=["Local"], uom=uom_kg, barcode="8964000330044", stock_qty=50)
except Exception as e:
    import traceback; traceback.print_exc()
    _log("failed", f"simple products: {e}")

# ----------------------------------------------------------------------------
# 5. Expiry-tracked product (Dairy) + a lot with expiration date
# ----------------------------------------------------------------------------
print("Expiry product:")
try:
    milk = env["product.template"].search([("default_code", "=", "OLPERS1L")], limit=1)
    if not milk:
        milk = env["product.template"].create({
            "name": "Olpers Milk 1L",
            "default_code": "OLPERS1L",
            "barcode": "8964000440055",
            "type": "consu",
            "is_storable": True,
            "available_in_pos": True,
            "list_price": 210,
            "standard_price": 180,
            "categ_id": pcateg["Dairy"].id,
            "pos_categ_ids": [(6, 0, [poscateg["Dairy"].id])],
            "uom_id": uom_unit.id,
            "brand_id": brands["Olpers"].id,
            "product_tag_ids": [(6, 0, [tags["Local"].id, tags["Halal"].id])],
            "tracking": "lot",
            "use_expiration_date": True,
            "expiration_time": 15,
        })
        _log("created", "product: Olpers Milk 1L (expiry, lot-tracked)")
    else:
        _log("skipped", "product: Olpers Milk 1L")
    milk_variant = milk.product_variant_id
    lot = env["stock.lot"].search([("product_id", "=", milk_variant.id), ("name", "=", "LOT-MILK-0001")], limit=1)
    if not lot:
        lot = env["stock.lot"].create({
            "name": "LOT-MILK-0001",
            "product_id": milk_variant.id,
            "expiration_date": date.today() + timedelta(days=12),
        })
        _log("created", "lot: LOT-MILK-0001 (exp +12d)")
    if env["stock.quant"]._get_available_quantity(milk_variant, stock_loc, lot_id=lot) < 40:
        env["stock.quant"]._update_available_quantity(milk_variant, stock_loc, 40, lot_id=lot)
        _log("created", "stock: Olpers Milk 1L +40 (lot)")
except Exception as e:
    import traceback; traceback.print_exc()
    _log("failed", f"expiry product: {e}")

# ----------------------------------------------------------------------------
# 6. Variant product (Apparel: Size S/M/L)
# ----------------------------------------------------------------------------
print("Variant product:")
try:
    size_attr = gc("product.attribute", [("name", "=", "Size")],
                   {"name": "Size", "create_variant": "always"}, "Size")
    size_vals = {}
    for v in ["S", "M", "L"]:
        size_vals[v] = gc("product.attribute.value",
                          [("name", "=", v), ("attribute_id", "=", size_attr.id)],
                          {"name": v, "attribute_id": size_attr.id}, f"Size={v}")
    tshirt = env["product.template"].search([("default_code", "=", "TSHIRT")], limit=1)
    if not tshirt:
        tshirt = env["product.template"].create({
            "name": "Cotton T-Shirt",
            "default_code": "TSHIRT",
            "type": "consu",
            "is_storable": True,
            "available_in_pos": True,
            "list_price": 500,
            "standard_price": 300,
            "categ_id": pcateg["Apparel"].id,
            "pos_categ_ids": [(6, 0, [poscateg["Apparel"].id])],
            "uom_id": uom_unit.id,
            "attribute_line_ids": [(0, 0, {
                "attribute_id": size_attr.id,
                "value_ids": [(6, 0, [size_vals[v].id for v in ["S", "M", "L"]])],
            })],
        })
        _log("created", "product: Cotton T-Shirt (S/M/L variants)")
    else:
        _log("skipped", "product: Cotton T-Shirt")
    for variant in tshirt.product_variant_ids:
        if env["stock.quant"]._get_available_quantity(variant, stock_loc) < 25:
            env["stock.quant"]._update_available_quantity(variant, stock_loc, 25)
    _log("created", "stock: T-Shirt variants +25 each")
except Exception as e:
    import traceback; traceback.print_exc()
    _log("failed", f"variant product: {e}")

# ----------------------------------------------------------------------------
# 7. Vendors + supplier info
# ----------------------------------------------------------------------------
print("Vendors:")
try:
    v1 = gc("res.partner", [("name", "=", "Karachi Beverages Distributors")], {
        "name": "Karachi Beverages Distributors",
        "company_type": "company",
        "supplier_rank": 1,
        "phone": "+92 21 111 222 333",
        "email": "sales@kbd.example.pk",
        "vat": "1234567-8",
        "street": "SITE Area", "city": "Karachi",
        "property_supplier_payment_term_id": term_30.id,
        "credit_limit": 500000,
    }, "Karachi Beverages Distributors")
    v2 = gc("res.partner", [("name", "=", "National Grocery Suppliers")], {
        "name": "National Grocery Suppliers",
        "company_type": "company",
        "supplier_rank": 1,
        "phone": "+92 42 999 888 777",
        "email": "info@ngs.example.pk",
        "vat": "8765432-1",
        "street": "Gulberg", "city": "Lahore",
        "property_supplier_payment_term_id": term_imm.id,
        "credit_limit": 300000,
    }, "National Grocery Suppliers")

    def supplierinfo(vendor, tmpl, price):
        if not tmpl:
            return
        exists = env["product.supplierinfo"].search(
            [("partner_id", "=", vendor.id), ("product_tmpl_id", "=", tmpl.id)], limit=1)
        if not exists:
            env["product.supplierinfo"].create({
                "partner_id": vendor.id, "product_tmpl_id": tmpl.id,
                "price": price, "min_qty": 1,
            })
            _log("created", f"supplierinfo: {vendor.name} -> {tmpl.name}")

    supplierinfo(v1, coke, 55)
    supplierinfo(v1, pepsi, 52)
    supplierinfo(v1, water, 40)
    supplierinfo(v2, masala, 90)
    supplierinfo(v2, sugar, 120)
except Exception as e:
    import traceback; traceback.print_exc()
    _log("failed", f"vendors: {e}")

# ----------------------------------------------------------------------------
# 8. Customers with membership level + birthday
# ----------------------------------------------------------------------------
print("Customers:")
try:
    def level(name):
        return env["pos.membership.level"].search([("name", "=", name)], limit=1)

    customers = [
        ("Ahmed Khan", "+92 300 1234567", "ahmed@example.pk", "Gold", date(1990, 3, 15)),
        ("Sara Malik", "+92 321 7654321", "sara@example.pk", "Silver", date(1995, 11, 2)),
        ("Bilal Raza", "+92 333 2223344", "bilal@example.pk", "VIP", date(1988, 7, 20)),
        ("Fatima Noor", "+92 345 5556677", "fatima@example.pk", "Bronze", date(2000, 1, 30)),
    ]
    for name, phone, email, lvl, bday in customers:
        gc("res.partner", [("name", "=", name)], {
            "name": name, "company_type": "person", "customer_rank": 1,
            "phone": phone, "email": email,
            "membership_level_id": level(lvl).id, "birthday": bday,
        }, f"{name} ({lvl})")
except Exception as e:
    import traceback; traceback.print_exc()
    _log("failed", f"customers: {e}")

# ----------------------------------------------------------------------------
# 9. JazzCash / EasyPaisa manual payment methods
# ----------------------------------------------------------------------------
print("Payment methods:")
try:
    def wallet_method(name, code):
        journal = env["account.journal"].search(
            [("code", "=", code), ("company_id", "=", company.id)], limit=1)
        if not journal:
            journal = env["account.journal"].create({
                "name": name, "type": "bank", "code": code, "company_id": company.id,
            })
            _log("created", f"journal: {name} ({code})")
        pm = env["pos.payment.method"].search(
            [("name", "=", name), ("company_id", "=", company.id)], limit=1)
        if not pm:
            pm = env["pos.payment.method"].create({
                "name": name, "journal_id": journal.id,
            })
            _log("created", f"pos.payment.method: {name}")
        return pm

    jazz = wallet_method("JazzCash", "JAZZ")
    easy = wallet_method("EasyPaisa", "EASY")
    for cfg in env["pos.config"].search([("company_id", "=", company.id)]):
        cfg.payment_method_ids = [(4, jazz.id), (4, easy.id)]
    _log("created", "payment methods linked to POS configs")
except Exception as e:
    import traceback; traceback.print_exc()
    _log("failed", f"payment methods: {e}")

# ----------------------------------------------------------------------------
# 10. Promotions (Loyalty programs)
# ----------------------------------------------------------------------------
print("Promotions:")
cur = company.currency_id.id


def make_program(name, program_type, rule_vals, reward_vals):
    prog = env["loyalty.program"].search([("name", "=", name)], limit=1)
    if prog:
        _log("skipped", f"promotion: {name}")
        return prog
    prog = env["loyalty.program"].create({
        "name": name,
        "program_type": program_type,
        "currency_id": cur,
        "rule_ids": [(0, 0, rule_vals)],
        "reward_ids": [(0, 0, reward_vals)],
    })
    _log("created", f"promotion: {name}")
    return prog


try:
    if coke:
        make_program(
            "Milk & Coke 20% Off", "promotion",
            {"product_ids": [(6, 0, [coke.product_variant_id.id])], "minimum_qty": 1},
            {"reward_type": "discount", "discount": 20, "discount_mode": "percent",
             "discount_applicability": "specific",
             "discount_product_ids": [(6, 0, [coke.product_variant_id.id])]},
        )
    make_program(
        "10% Off Orders Over 5000", "promotion",
        {"minimum_amount": 5000},
        {"reward_type": "discount", "discount": 10, "discount_mode": "percent",
         "discount_applicability": "order"},
    )
    bev_variants = env["product.product"].search([("categ_id", "=", pcateg["Beverages"].id)])
    if bev_variants:
        make_program(
            "All Beverages 20% Off", "promotion",
            {"product_category_id": pcateg["Beverages"].id, "minimum_qty": 1},
            {"reward_type": "discount", "discount": 20, "discount_mode": "percent",
             "discount_applicability": "specific",
             "discount_product_ids": [(6, 0, bev_variants.ids)]},
        )
    if coke:
        make_program(
            "Buy 1 Coke Get 1 Free", "buy_x_get_y",
            {"product_ids": [(6, 0, [coke.product_variant_id.id])], "minimum_qty": 1,
             "reward_point_amount": 1, "reward_point_mode": "unit"},
            {"reward_type": "product", "reward_product_id": coke.product_variant_id.id,
             "reward_product_qty": 1, "required_points": 1},
        )
except Exception as e:
    import traceback; traceback.print_exc()
    _log("failed", f"promotions: {e}")

# ----------------------------------------------------------------------------
# Commit + summary
# ----------------------------------------------------------------------------
env.cr.commit()
print("\n==================== SAMPLE STORE SUMMARY ====================")
print(f"  created: {len(report['created'])}")
print(f"  skipped: {len(report['skipped'])}")
print(f"  failed : {len(report['failed'])}")
if report["failed"]:
    print("  FAILURES:")
    for f in report["failed"]:
        print("   -", f)
print("=============================================================")
print("SETUP_DONE")
