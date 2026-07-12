# -*- coding: utf-8 -*-
"""
Part 2 of the sample-store setup: operational flows + the remaining offer types.
Run AFTER setup_sample_store.py, in the Odoo shell (commits at the end):

    venv\\Scripts\\python.exe odoo\\odoo-bin shell -c odoo.conf -d learningO --no-http < custom_addons/pos_retail/scripts/setup_operations_demo.py

Adds: the rest of the Discounts & Offers list (buy-2-get-50%, spend-based gift,
coupon code, loyalty points earn+redeem, combo), a full Purchase Order ->
Receive -> Vendor Bill flow (feeds vendor ledger / outstanding balance /
purchase reports / stock-in), a scrap (damaged) order, an inventory adjustment,
POS receipt header/footer config, and cashier employees with POS PINs.

Safe to re-run: everything is looked up by a natural key first.
"""
from datetime import date, datetime, timedelta

report = {"created": [], "skipped": [], "failed": []}


def _log(kind, label):
    report[kind].append(label)
    print(f"  [{kind.upper():7}] {label}")


company = env.company
warehouse = env["stock.warehouse"].search([("company_id", "=", company.id)], limit=1)
stock_loc = warehouse.lot_stock_id
cur = company.currency_id.id


def P(code):
    return env["product.template"].search([("default_code", "=", code)], limit=1)


def categ(name):
    return env["product.category"].search([("name", "=", name)], limit=1)


coke, pepsi, water = P("COKE500"), P("PEPSI500"), P("WATER15")
lays, masala, sugar = P("LAYS-CL"), P("NAT-MASALA"), P("SUGAR-KG")
v1 = env["res.partner"].search([("name", "=", "Karachi Beverages Distributors")], limit=1)

print(f"\nOperations demo for '{company.name}' ...\n")


# ----------------------------------------------------------------------------
# A. Remaining Discounts & Offers
# ----------------------------------------------------------------------------
print("Offers:")


def make_program(name, program_type, rule_vals, reward_vals):
    prog = env["loyalty.program"].search([("name", "=", name)], limit=1)
    if prog:
        _log("skipped", f"promotion: {name}")
        return prog
    prog = env["loyalty.program"].create({
        "name": name, "program_type": program_type, "currency_id": cur,
        "rule_ids": [(0, 0, rule_vals)], "reward_ids": [(0, 0, reward_vals)],
    })
    _log("created", f"promotion: {name}")
    return prog


try:
    make_program(
        "Buy 2 Snacks, 50% Off 3rd", "promotion",
        {"product_category_id": categ("Snacks").id, "minimum_qty": 3},
        {"reward_type": "discount", "discount": 50, "discount_mode": "percent",
         "discount_applicability": "cheapest"},
    )
    if water:
        make_program(
            "Spend 5000, Free Water", "promotion",
            {"minimum_amount": 5000},
            {"reward_type": "product", "reward_product_id": water.product_variant_id.id,
             "reward_product_qty": 1, "required_points": 1},
        )
    # Discount code the customer types at POS
    prog = env["loyalty.program"].search([("name", "=", "Coupon WELCOME10")], limit=1)
    if not prog:
        prog = env["loyalty.program"].create({
            "name": "Coupon WELCOME10", "program_type": "promo_code", "currency_id": cur,
            "rule_ids": [(0, 0, {"mode": "with_code", "code": "WELCOME10"})],
            "reward_ids": [(0, 0, {"reward_type": "discount", "discount": 10,
                                   "discount_mode": "percent", "discount_applicability": "order"})],
        })
        _log("created", "promotion: Coupon WELCOME10")
    else:
        _log("skipped", "promotion: Coupon WELCOME10")
    # Loyalty points: earn 1 pt / 100 spent, redeem 100 pts = 100 off
    make_program(
        "Shop Rewards Points", "loyalty",
        {"reward_point_mode": "money", "reward_point_amount": 0.01, "minimum_amount": 0},
        {"reward_type": "discount", "discount": 1, "discount_mode": "per_point",
         "discount_applicability": "order", "required_points": 100},
    )
except Exception as e:
    import traceback; traceback.print_exc()
    _log("failed", f"offers: {e}")


# ----------------------------------------------------------------------------
# B. Combo product (Burger/Fries/Drink style, using our catalog)
# ----------------------------------------------------------------------------
print("Combo:")
try:
    def get_combo(name, product_tmpls):
        c = env["product.combo"].search([("name", "=", name)], limit=1)
        if c:
            _log("skipped", f"combo choice: {name}")
            return c
        c = env["product.combo"].create({
            "name": name,
            "combo_item_ids": [(0, 0, {"product_id": t.product_variant_id.id, "extra_price": 0.0})
                               for t in product_tmpls if t],
        })
        _log("created", f"combo choice: {name}")
        return c

    drink = get_combo("Choose a Drink", [coke, pepsi, water])
    snack = get_combo("Choose a Snack", [lays, masala])
    combo_tmpl = env["product.template"].search([("default_code", "=", "COMBO1")], limit=1)
    if not combo_tmpl:
        combo_tmpl = env["product.template"].create({
            "name": "Snack + Drink Combo",
            "default_code": "COMBO1",
            "type": "combo",
            "available_in_pos": True,
            "list_price": 120,
            "combo_ids": [(6, 0, [drink.id, snack.id])],
        })
        _log("created", "product: Snack + Drink Combo (type=combo)")
    else:
        _log("skipped", "product: Snack + Drink Combo")
except Exception as e:
    import traceback; traceback.print_exc()
    _log("failed", f"combo: {e}")


# ----------------------------------------------------------------------------
# C. Purchase Order -> Receive -> Vendor Bill
# ----------------------------------------------------------------------------
print("Purchase flow:")
try:
    po = env["purchase.order"].search([("partner_ref", "=", "DEMO-PO-1")], limit=1)
    if not po:
        po = env["purchase.order"].create({
            "partner_id": v1.id,
            "partner_ref": "DEMO-PO-1",
            "order_line": [
                (0, 0, {"product_id": coke.product_variant_id.id, "product_qty": 50,
                        "price_unit": 55, "name": coke.name,
                        "date_planned": datetime.now(), "product_uom_id": coke.uom_id.id}),
                (0, 0, {"product_id": water.product_variant_id.id, "product_qty": 40,
                        "price_unit": 40, "name": water.name,
                        "date_planned": datetime.now(), "product_uom_id": water.uom_id.id}),
            ],
        })
        _log("created", f"purchase.order: {po.name} (DEMO-PO-1)")
        po.button_confirm()
        _log("created", f"PO confirmed -> state={po.state}")
        # receive
        for picking in po.picking_ids:
            picking.action_assign()
            for m in picking.move_ids:
                m.quantity = m.product_uom_qty
                m.picked = True
            res = picking.with_context(skip_backorder=True, skip_sms=True).button_validate()
            if isinstance(res, dict) and res.get("res_model") == "stock.backorder.confirmation":
                wiz = env[res["res_model"]].with_context(res.get("context", {})).create({})
                wiz.process()
            _log("created", f"receipt {picking.name} -> state={picking.state}")
        # vendor bill
        po.action_create_invoice()
        for bill in po.invoice_ids:
            if bill.state == "draft":
                bill.invoice_date = date.today()
                bill.ref = "BILL-KBD-001"
                bill.action_post()
                _log("created", f"vendor bill {bill.name} posted, total={bill.amount_total}")
    else:
        _log("skipped", f"purchase.order: {po.name}")
except Exception as e:
    import traceback; traceback.print_exc()
    _log("failed", f"purchase flow: {e}")


# ----------------------------------------------------------------------------
# D. Inventory: scrap (damaged) + adjustment
# ----------------------------------------------------------------------------
print("Inventory ops:")
try:
    existing_scrap = env["stock.scrap"].search(
        [("product_id", "=", lays.product_variant_id.id), ("state", "=", "done")], limit=1)
    if not existing_scrap:
        scrap = env["stock.scrap"].create({
            "product_id": lays.product_variant_id.id,
            "scrap_qty": 5,
            "location_id": stock_loc.id,
            "origin": "DEMO-DAMAGED",
        })
        scrap.do_scrap()
        _log("created", f"scrap (damaged): 5x {lays.name} -> {scrap.state}")
    else:
        _log("skipped", "scrap (damaged): Lays")

    # Inventory adjustment: set Pepsi on-hand to 100
    quant = env["stock.quant"].search(
        [("product_id", "=", pepsi.product_variant_id.id), ("location_id", "=", stock_loc.id)], limit=1)
    if quant and quant.quantity != 100:
        quant.inventory_quantity = 100
        quant.action_apply_inventory()
        _log("created", f"inventory adjustment: {pepsi.name} on-hand -> 100")
    else:
        _log("skipped", "inventory adjustment: Pepsi already 100")
except Exception as e:
    import traceback; traceback.print_exc()
    _log("failed", f"inventory ops: {e}")


# ----------------------------------------------------------------------------
# E. Receipt config (header/footer) + company address
# ----------------------------------------------------------------------------
print("Receipt config:")
try:
    header = "Smart Retail Store\nMain Boulevard, Lahore\nUAN: 111-222-333"
    footer = "Thank you for shopping!\nReturns within 7 days with receipt.\nFollow us @smartretail"
    n = 0
    for cfg in env["pos.config"].search([("company_id", "=", company.id)]):
        cfg.write({"receipt_header": header, "receipt_footer": footer})
        n += 1
    _log("created", f"receipt header/footer set on {n} POS config(s)")
    if not company.street:
        company.write({"street": "Main Boulevard", "city": "Lahore", "phone": "111-222-333"})
        _log("created", "company address set")
except Exception as e:
    import traceback; traceback.print_exc()
    _log("failed", f"receipt config: {e}")


# ----------------------------------------------------------------------------
# F. Cashier employees with POS PIN (Phase 2 groundwork)
# ----------------------------------------------------------------------------
print("Cashiers:")
try:
    for name, pin in [("Cashier Ali", "1111"), ("Cashier Zara", "2222")]:
        emp = env["hr.employee"].search([("name", "=", name)], limit=1)
        if not emp:
            env["hr.employee"].create({"name": name, "pin": pin})
            _log("created", f"employee: {name} (PIN set)")
        else:
            _log("skipped", f"employee: {name}")
except Exception as e:
    import traceback; traceback.print_exc()
    _log("failed", f"cashiers: {e}")


# ----------------------------------------------------------------------------
# Commit + summary
# ----------------------------------------------------------------------------
env.cr.commit()
print("\n================= OPERATIONS DEMO SUMMARY =================")
print(f"  created: {len(report['created'])}")
print(f"  skipped: {len(report['skipped'])}")
print(f"  failed : {len(report['failed'])}")
if report["failed"]:
    print("  FAILURES:")
    for f in report["failed"]:
        print("   -", f)
print("==========================================================")
print("OPS_DONE")
