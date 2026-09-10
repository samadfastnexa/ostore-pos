"""What does the parent company actually own, and what could safely go?

    sudo -u odoo /opt/odoo/venv/bin/python3 /opt/odoo/odoo/odoo-bin shell \
        -c /etc/odoo/odoo.conf -d ostore_live --no-http \
        < /opt/odoo/custom_addons/pos_retail/scripts/audit_parent_company_data.py

Writes nothing. There is no APPLY switch in this file at all, deliberately:
the answer to "delete everything on the parent" is not a flag, it is a list
of decisions, and each one needs looking at before it is made.

THE SHAPE OF THIS BUSINESS. The parent holds the legal identity. Every shop
is a branch that owns its own catalogue, customers, khata, till and
expenses. So the instinct that the parent should hold no trading data is
right. Acting on it is still not a single delete, for three reasons.

  1. THE PARENT HAS TRADED. There are real POS orders on it from before the
     branches were split out. Sales records carry journal entries and tax,
     and a business is required to keep them. Archiving hides them from
     daily use; deleting destroys them.

  2. SHARED IS NOT THE PARENT'S. A record with no company at all belongs to
     every company, both branches included. It sorts next to the parent's
     records and reads like one of them. Deleting a shared product empties
     that product out of the branches too.

  3. ODOO WILL REFUSE MOST OF IT ANYWAY. A product on an order line, a
     partner on an invoice, a journal with entries -- all are protected by
     foreign keys, and the delete fails partway leaving a half-cleaned
     company. Anything reachable from a document has to be archived instead.

So this reports three groups per model: what the parent owns, how much of
that is referenced by a document and therefore not deletable, and what is
shared rather than the parent's at all.
"""

Company = env['res.company'].sudo()
parents = Company.search([('parent_id', '=', False)])
branches = Company.search([('parent_id', '!=', False)])

line_break = "=" * 78
print()
print(line_break)
print("WHAT THE PARENT COMPANY OWNS")
print(line_break)
print()
print("  Parent  : %s" % ", ".join("%s (id %s)" % (c.name, c.id) for c in parents))
print("  Branches: %s" % ", ".join("%s (id %s)" % (c.name, c.id) for c in branches))

# model, label, and the field naming the document that would protect a record
# from deletion. None means "count only, nothing protects it".
GROUPS = [
    ('product.template', "Products (templates)"),
    ('product.product', "Product variants"),
    ('res.partner', "Contacts"),
    ('pos.config', "Registers"),
    ('pos.session', "POS sessions"),
    ('pos.order', "POS orders"),
    ('account.move', "Invoices / journal entries"),
    ('account.journal', "Journals"),
    ('purchase.order', "Purchase orders"),
    ('sale.order', "Sales orders"),
    ('stock.warehouse', "Warehouses"),
    ('stock.picking', "Stock transfers"),
    ('stock.quant', "Stock on hand"),
    ('hr.employee', "Employees"),
]

print()
print("  %-28s %8s %8s %8s" % ("", "PARENT", "SHARED", "BRANCHES"))
print("  %-28s %8s %8s %8s" % ("", "------", "------", "--------"))

for model_name, label in GROUPS:
    Model = env.get(model_name)
    if Model is None:
        continue
    Model = Model.sudo().with_context(active_test=False)
    if 'company_id' not in Model._fields:
        continue
    try:
        on_parent = Model.search_count([('company_id', 'in', parents.ids)])
        shared = Model.search_count([('company_id', '=', False)])
        on_branch = Model.search_count([('company_id', 'in', branches.ids)])
    except Exception as err:
        print("  %-28s  could not count: %s" % (label, err))
        continue
    flag = "  <-- has data" if on_parent else ""
    print("  %-28s %8s %8s %8s%s" % (label, on_parent, shared, on_branch, flag))

print()
print(line_break)
print("WHAT IS PROTECTED, AND WHY")
print(line_break)

PosOrder = env['pos.order'].sudo()
Move = env['account.move'].sudo()

orders = PosOrder.search([('company_id', 'in', parents.ids)])
if orders:
    total = sum(orders.mapped('amount_total'))
    currency = orders[0].currency_id.name if orders[0].currency_id else ""
    print()
    print("  POS ORDERS ON THE PARENT: %s order(s), %s %s" % (len(orders), total, currency))
    print("      Dates: %s to %s" % (
        min(orders.mapped('date_order')).strftime("%Y-%m-%d"),
        max(orders.mapped('date_order')).strftime("%Y-%m-%d")))
    print("      These are real sales. They carry journal entries and tax, and a")
    print("      business has to be able to produce them. Deleting them is not the")
    print("      same as tidying a dashboard.")
    sessions = orders.mapped('session_id')
    print("      Held in %s session(s) on %s register(s)." % (
        len(sessions), len(sessions.mapped('config_id'))))

moves = Move.search([('company_id', 'in', parents.ids), ('state', '=', 'posted')])
if moves:
    print()
    print("  POSTED ACCOUNTING ENTRIES ON THE PARENT: %s" % len(moves))
    print("      A posted entry cannot be deleted at all, only reversed. Odoo")
    print("      enforces this, and so does every tax authority.")

# Products the parent owns that something already refers to. Counted through
# the order lines rather than by trying a delete, because a failed delete on a
# live database is not a diagnostic anyone wants to run.
Product = env['product.product'].sudo().with_context(active_test=False)
parent_products = Product.search([('company_id', 'in', parents.ids)])
if parent_products:
    PosLine = env['pos.order.line'].sudo()
    used = PosLine.search([('product_id', 'in', parent_products.ids)]).mapped('product_id')
    print()
    print("  PRODUCTS OWNED BY THE PARENT: %s" % len(parent_products))
    print("      of which already sold at least once: %s  (cannot be deleted)" % len(used))
    print("      never sold: %s  (deletable, unless referenced elsewhere)"
          % (len(parent_products) - len(used)))
    for product in parent_products[:15]:
        print("          %-40r %s" % (
            product.display_name[:38],
            "SOLD" if product in used else "never sold"))
    if len(parent_products) > 15:
        print("          ... and %s more" % (len(parent_products) - 15))

print()
print(line_break)
print("WHAT I WOULD ACTUALLY DO")
print(line_break)
print("""
  Archive, do not delete, anything the parent has traded. It disappears from
  every list and every dashboard, which is the outcome asked for, and the
  records survive for the day someone needs them.

  Delete outright only what has never been used: the empty register, and any
  product on the parent that has never been sold, received or ordered.

  Leave shared records alone entirely. They are not the parent's.

  If the goal is that nobody can trade on the parent again, the reliable way
  is not deleting rows. It is that the parent has no active register, which
  fix_stray_registers.py already handles.
""")
print(line_break)
print("Nothing was written.")
print(line_break)
