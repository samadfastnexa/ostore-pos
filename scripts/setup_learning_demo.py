# -*- coding: utf-8 -*-
"""
Part 3 of the sample-store setup: the modules the first two scripts leave empty.
Run AFTER setup_sample_store.py and setup_operations_demo.py, in the Odoo shell:

    venv\\Scripts\\python.exe odoo\\odoo-bin shell -c odoo.conf -d OStore --no-http < custom_addons/pos_retail/scripts/setup_learning_demo.py

Parts 1 and 2 already cover brands, categories, products, expiry lots, variants,
vendors, customers, payment methods, promotions, the purchase->receive->bill
flow, scrap, inventory adjustments, receipt config and cashiers. What stays at
zero after them -- and therefore leaves whole menus looking broken while you are
learning -- is filled in here:

  * customer-type pricelist RULES (the six pricelists ship empty by design)
  * business expenses across categories and months (expense reports, dashboard)
  * customer ledger adjustments / opening khata balances (customer ledger)
  * quotations (the pos_sale "settle a quotation at the till" flow)
  * a few more customers so Top Customers and the ledger are not single-row

NOTE ON ACCOUNTING: confirming a ledger adjustment POSTS a real journal entry
(pos_retail_ledger_adjustment.action_confirm). That is the point -- it is how the
customer ledger gets rows -- but it means this script writes to your books. Do
not run it against a database you intend to use for real trading.

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
today = date.today()
print(f"\nLearning demo for '{company.name}' ...\n")

# ---------------------------------------------------------------------------
# 1. Pricelist rules
# ---------------------------------------------------------------------------
# The shipped pricelists are deliberately empty (see data/pos_retail_pricelist_data.xml),
# which is correct for a real store but means "Wholesale" and "Retail" look
# identical while you are learning. Give each a single global rule so switching
# pricelist at the till visibly moves the price.
print("Pricelist rules:")
PRICELIST_MARKDOWN = [
    ("pos_retail.pricelist_retail", 0.0),
    ("pos_retail.pricelist_wholesale", 10.0),
    ("pos_retail.pricelist_dealer", 15.0),
    ("pos_retail.pricelist_distributor", 20.0),
    ("pos_retail.pricelist_vip", 5.0),
    ("pos_retail.pricelist_corporate", 8.0),
]
for xmlid, discount in PRICELIST_MARKDOWN:
    pricelist = env.ref(xmlid, raise_if_not_found=False)
    if not pricelist:
        _log("failed", f"{xmlid} missing -- upgrade pos_retail first")
        continue
    if not discount:
        _log("skipped", f"product.pricelist.item: {pricelist.name} (list price, no rule needed)")
        continue
    gc(
        "product.pricelist.item",
        [("pricelist_id", "=", pricelist.id), ("applied_on", "=", "3_global")],
        {
            "pricelist_id": pricelist.id,
            "applied_on": "3_global",
            "compute_price": "percentage",
            "percent_price": discount,
        },
        f"{pricelist.name}: -{discount:g}% on everything",
    )

# ---------------------------------------------------------------------------
# 2. Business expenses
# ---------------------------------------------------------------------------
# Spread over three months so the expense reports have something to group by and
# the dashboard's period comparison is not comparing a month against nothing.
print("Expenses:")
EXPENSES = [
    ("Shop rent", "rent", 85000, "bank", 0),
    ("Electricity bill", "electricity", 24500, "bank", 3),
    ("Staff salaries", "salaries", 145000, "bank", 5),
    ("Internet & POS line", "internet", 6500, "bank", 8),
    ("Delivery van fuel", "fuel", 18000, "cash", 11),
    ("Chiller servicing", "maintenance", 9500, "cash", 16),
    ("Ramadan banner printing", "marketing", 12000, "cash", 22),
    ("Shop rent", "rent", 85000, "bank", 31),
    ("Electricity bill", "electricity", 31200, "bank", 34),
    ("Staff salaries", "salaries", 145000, "bank", 36),
    ("Generator diesel", "fuel", 22000, "cash", 41),
    ("Shelf repairs", "maintenance", 7800, "cash", 48),
    ("Shop rent", "rent", 85000, "bank", 62),
    ("Electricity bill", "electricity", 28700, "bank", 65),
    ("Staff salaries", "salaries", 145000, "bank", 67),
    ("Tea & cleaning supplies", "miscellaneous", 4300, "cash", 73),
]
for name, category, amount, method, days_ago in EXPENSES:
    when = today - timedelta(days=days_ago)
    gc(
        "pos.retail.expense",
        [("name", "=", name), ("date", "=", when)],
        {
            "name": name,
            "category": category,
            "amount": amount,
            "payment_method": method,
            "date": when,
        },
        f"{name} {amount:,.0f} on {when}",
    )

# ---------------------------------------------------------------------------
# 3. Extra customers
# ---------------------------------------------------------------------------
# Enough variety that Top Customers, the membership filters and the ledger all
# show more than one row. customer_rank=1 is what puts them in customer lists.
print("Customers:")
levels = {lvl.name: lvl for lvl in env["pos.membership.level"].search([])}
CUSTOMERS = [
    ("Bilal Traders", "Gold", "0300-1234567", 150000),
    ("Sana General Store", "Silver", "0321-9876543", 80000),
    ("Hassan Kiryana", "Bronze", "0333-5551212", 40000),
    ("Mehwish Cash & Carry", "VIP", "0345-7778888", 300000),
    ("Usman Corner Shop", "Bronze", "0301-2223333", 25000),
]
customers = []
for name, level_name, mobile, credit_limit in CUSTOMERS:
    vals = {
        "name": name,
        "customer_rank": 1,
        "mobile": mobile,
        "pos_credit_limit": credit_limit,
    }
    if level_name in levels:
        vals["membership_level_id"] = levels[level_name].id
    customers.append(gc("res.partner", [("name", "=", name)], vals, f"{name} ({level_name})"))

# ---------------------------------------------------------------------------
# 4. Customer ledger adjustments
# ---------------------------------------------------------------------------
# Opening balances carried over from a paper khata, plus one waiver, so the
# customer ledger and the outstanding-balance figures have real rows behind them.
print("Ledger adjustments:")
journal = env["account.journal"].search(
    [("type", "=", "general"), ("company_id", "=", company.id)], limit=1)
equity = env["account.account"].search(
    [("account_type", "=", "equity"), ("company_ids", "in", company.id)], limit=1)
expense_acc = env["account.account"].search(
    [("account_type", "=", "expense"), ("company_ids", "in", company.id)], limit=1)

if not (journal and equity and expense_acc):
    _log("failed", "ledger adjustments: no general journal / equity / expense account found")
else:
    ADJUSTMENTS = [
        (0, "increase", 45000, "Opening balance carried from khata", equity),
        (1, "increase", 18500, "Opening balance carried from khata", equity),
        (2, "increase", 7200, "Opening balance carried from khata", equity),
        (2, "decrease", 2200, "Goodwill waiver on damaged stock", expense_acc),
    ]
    for idx, direction, amount, reason, account in ADJUSTMENTS:
        if idx >= len(customers):
            continue
        partner = customers[idx]
        existing = env["pos.retail.ledger.adjustment"].search(
            [("partner_id", "=", partner.id), ("reason", "=", reason)], limit=1)
        if existing:
            _log("skipped", f"pos.retail.ledger.adjustment: {partner.name} / {reason}")
            continue
        adj = env["pos.retail.ledger.adjustment"].create({
            "partner_id": partner.id,
            "direction": direction,
            "amount": amount,
            "reason": reason,
            "counterpart_account_id": account.id,
            "journal_id": journal.id,
            "date": today - timedelta(days=20),
        })
        # Posts the journal entry -- without this the ledger stays empty.
        adj.action_confirm()
        _log("created", f"pos.retail.ledger.adjustment: {partner.name} {direction} {amount:,.0f}")

# ---------------------------------------------------------------------------
# 5. Quotations
# ---------------------------------------------------------------------------
# pos_sale lets a cashier pull a quotation into the till and settle it. With no
# sale.order in the database that button looks broken, so seed a few.
print("Quotations:")
sellable = env["product.product"].search(
    [("sale_ok", "=", True), ("type", "!=", "combo")], limit=6)
if not sellable:
    _log("failed", "quotations: no sellable products found")
else:
    QUOTATIONS = [
        ("Bilal Traders", 0, [(0, 20), (1, 12)], True),
        ("Sana General Store", 1, [(2, 8), (3, 5)], True),
        ("Mehwish Cash & Carry", 3, [(0, 50), (4, 30)], False),
    ]
    for label, cust_idx, lines, confirm in QUOTATIONS:
        if cust_idx >= len(customers):
            continue
        partner = customers[cust_idx]
        origin = f"Learning demo quotation - {label}"
        existing = env["sale.order"].search([("origin", "=", origin)], limit=1)
        if existing:
            _log("skipped", f"sale.order: {label}")
            continue
        order_lines = []
        for prod_idx, qty in lines:
            if prod_idx >= len(sellable):
                continue
            product = sellable[prod_idx]
            order_lines.append((0, 0, {"product_id": product.id, "product_uom_qty": qty}))
        if not order_lines:
            continue
        order = env["sale.order"].create({
            "partner_id": partner.id,
            "origin": origin,
            "order_line": order_lines,
        })
        if confirm:
            order.action_confirm()
        _log("created", f"sale.order: {order.name} for {partner.name}"
                        f"{' (confirmed)' if confirm else ' (draft quotation)'}")

# ---------------------------------------------------------------------------
env.cr.commit()

print("\n================= LEARNING DEMO SUMMARY =================")
print(f"  created: {len(report['created'])}")
print(f"  skipped: {len(report['skipped'])}")
print(f"  failed : {len(report['failed'])}")
for label in report["failed"]:
    print(f"    FAILED: {label}")
print("=========================================================")
print("LEARNING_DONE")
