"""Adopt SHARED products into one branch. The production-shaped migration.

The laptop migration moved an OWNED catalogue (copy_catalogue_to_branch.py).
Production grew differently: its catalogue is SHARED (company_id empty), which
the branch rules deliberately show to every company -- so the parent still
lists every product, and "the parent sells nothing" can never pass while the
goods have no owner.

Per shared product, in order:

  1. Try simply setting company_id to the branch. Works when no stock move of
     the product exists in any OTHER company.
  2. Otherwise: zero the product's stock held by other companies (real
     inventory adjustments, so valuation stays consistent), ARCHIVE the shared
     original, then create a branch-owned copy carrying the same name, code
     and barcode, and count the stock into the branch warehouse.

     The order is the whole trick. A SHARED product occupies every company's
     barcode namespace, so creating the branch copy while the original is
     active collides. Archiving first frees the barcode (the uniqueness check
     ignores archived records), and the copy then takes it -- one printed
     shelf label keeps scanning.

Every write is re-read and verified; any unverified step rolls the whole run
back. DRY_RUN by default.

Run:
    venv/Scripts/python.exe odoo/odoo-bin shell -c odoo.conf -d <db> --no-http         < custom_addons/pos_retail/scripts/adopt_shared_catalogue.py
"""

TARGET_COMPANY_ID = None      # None = the first branch (company with a parent)
ALSO_ADOPT_PARENT_OWNED = True  # products the PARENT owns move to the branch too
DRY_RUN = True

Company = env['res.company'].sudo()
Template = env['product.template'].sudo()
Quant = env['stock.quant'].sudo()
Move = env['stock.move'].sudo()
Warehouse = env['stock.warehouse'].sudo()

dst = (Company.browse(TARGET_COMPANY_ID) if TARGET_COMPANY_ID
       else Company.search([('parent_id', '!=', False)], limit=1))
if not dst:
    raise UserError("No branch company found to adopt the catalogue into.")

problems = []


def verify(label, condition, detail=""):
    if condition:
        print("    verified: %s %s" % (label, detail))
    else:
        problems.append("%s %s" % (label, detail))
        print("    *** NOT VERIFIED: %s %s" % (label, detail))


print("=" * 76)
print("ADOPT SHARED CATALOGUE -> %s   %s" % (dst.name, "(DRY RUN)" if DRY_RUN else "(WRITING)"))
print("=" * 76)

wh = Warehouse.search([('company_id', '=', dst.id)], limit=1)
if not wh:
    raise UserError("%s has no warehouse; commission the branch first." % dst.name)
print("  branch warehouse: %s" % wh.name)

shared = Template.search([('company_id', '=', False)])

# Products the parent company owns are adopted as well, so the branch ends up
# holding everything the shop actually sells and the parent is left as the
# legal shell it is meant to be. Same two-path treatment: reassign when
# nothing blocks it, archive-and-copy when stock moves do.
if ALSO_ADOPT_PARENT_OWNED:
    parents = Company.search([('parent_id', '=', False)])
    parent_owned = Template.search([('company_id', 'in', parents.ids)])
    if parent_owned:
        print("  parent-owned products also being adopted: %s" % len(parent_owned))
    shared |= parent_owned

# What must STAY shared, learned by rehearsing this on a copy of the data:
#
#  * Anything a register or a loyalty programme points at. The Gift Card
#    product is shared AND is the reward product of a programme owned by the
#    parent; handing it to one branch breaks that programme everywhere else.
#    Searched with active_test=False because the discount product is commonly
#    ARCHIVED while still being every register's discount_product_id -- an
#    active-only search reports a protection it is not actually applying.
#  * Anything that is not physical stock. Down Payment, Gift Card, Top-up
#    eWallet and the discount line are cross-company plumbing, not goods on a
#    shelf, and no branch should own them.
#
# What gets adopted is what the shop actually sells.
pinned = Template.browse()
Config = env['pos.config'].sudo().with_context(active_test=False)
for c in Config.search([]):
    for fname, f in c._fields.items():
        if f.type == 'many2one' and f.store and f.comodel_name in ('product.product', 'product.template'):
            val = c[fname]
            if val:
                pinned |= val.product_tmpl_id if f.comodel_name == 'product.product' else val
if 'loyalty.program' in env:
    for prog in env['loyalty.program'].sudo().with_context(active_test=False).search([]):
        for rw in prog.reward_ids:
            if rw.discount_line_product_id:
                pinned |= rw.discount_line_product_id.product_tmpl_id
        for tr in getattr(prog, 'trigger_product_ids', Template.browse()):
            pinned |= tr.product_tmpl_id

keep = (shared & pinned) | shared.filtered(lambda t: not t.is_storable)
todo = shared - keep
print("  shared products: %s   kept shared on purpose: %s" % (len(shared), len(keep)))
for t in keep:
    why = "referenced by a register or programme" if t in pinned else "not physical stock"
    print("      keep %-26s (%s)" % (t.name[:26], why))

assigned, copied, failed = [], [], []
for tmpl in todo:
    variants = tmpl.product_variant_ids
    foreign_moves = Move.search_count([
        ('product_id', 'in', variants.ids),
        ('company_id', 'not in', [dst.id, False]),
    ])
    held = {}
    for v in variants:
        quants = Quant.search([('product_id', '=', v.id),
                               ('location_id.usage', '=', 'internal'),
                               ('company_id', '!=', dst.id)])
        qty = sum(quants.mapped('quantity'))
        if qty:
            held[v.id] = (quants, qty)

    if not foreign_moves:
        if DRY_RUN:
            assigned.append(tmpl.name)
            continue
        tmpl.write({'company_id': dst.id})
        tmpl.invalidate_recordset()
        (assigned if tmpl.company_id == dst else failed).append(tmpl.name)
        continue

    if DRY_RUN:
        copied.append(tmpl.name)
        continue
    try:
        # 1. take the stock out of the other companies first, while the
        #    original is still active (adjustments refuse archived products)
        total_qty = 0
        for v_id, (quants, qty) in held.items():
            for q in quants:
                q.with_context(inventory_mode=True).inventory_quantity = 0
            quants.with_context(inventory_mode=True).action_apply_inventory()
            total_qty += qty
        # 2. archive the shared original, freeing its barcode everywhere
        tmpl.write({'active': False})
        # 3. branch-owned copy, same identity, same label on the shelf
        new = tmpl.with_company(dst).copy({
            'name': tmpl.name,
            'company_id': dst.id,
            'default_code': tmpl.default_code,
            'barcode': tmpl.barcode,
            'active': True,
        })
        # 4. the goods are physically at the shop: count them in there
        if total_qty:
            q = Quant.with_company(dst).with_context(inventory_mode=True).create({
                'product_id': new.product_variant_id.id,
                'location_id': wh.lot_stock_id.id,
                'inventory_quantity': total_qty,
            })
            q.action_apply_inventory()
        copied.append(tmpl.name)
    except Exception as exc:
        failed.append("%s: %s" % (tmpl.name, str(exc)[:90]))

print("")
print("  assign directly : %s" % len(assigned))
print("  archive-and-copy: %s" % len(copied))
for name in failed:
    print("  FAILED: %s" % name)

if not DRY_RUN:
    verify("no failures", not failed, "(%s)" % len(failed))
    still = Template.search_count([('company_id', '=', False)]) - len(keep)
    verify("no shared product left unowned", still <= 0, "%s remain" % still)
    leftover = Quant.search([('company_id', '!=', dst.id),
                             ('location_id.usage', '=', 'internal'),
                             ('quantity', '!=', 0),
                             ('product_id.product_tmpl_id', 'in', (todo).ids)])
    verify("no stock left behind in other companies", not leftover,
           "%s quant lines" % len(leftover))

print()
if DRY_RUN:
    env.cr.rollback()
    print("DRY RUN complete, nothing written. Set DRY_RUN = False to apply.")
elif problems:
    env.cr.rollback()
    print("ROLLED BACK, %s step(s) unverified:" % len(problems))
    for p in problems:
        print("  - %s" % p)
else:
    env.cr.commit()
    print("Committed, every step verified.")
print("=" * 76)
