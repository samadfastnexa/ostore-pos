"""Give a branch its own catalogue and stop the parent company trading.

Target shape (see the branch-architecture note): the parent holds ONLY the
legal identity -- chart of accounts, NTN, taxes -- and every shop is an equal
branch owning its own catalogue, customers, khata, till and expenses.

MOVING the products is not possible. stock/models/product.py:1115 refuses a
company change while ANY stock move of that product exists in another company,
and counting the stock down to zero to satisfy the sibling quantity check
creates exactly those moves. There is no ordering that works, and the refusal
is right: a stock move carries a valuation entry, so re-stamping the owner
would leave the parent's books holding value for goods it no longer owns.

So the catalogue is COPIED into the branch and the parent's originals are
archived. The originals keep their own history, which is where it belongs.

ORDER MATTERS, and every step here was learned by getting it wrong:

  1. Partners referenced by ANOTHER company's records are made SHARED first.
     Move one into a branch and the branch record rule then denies the
     referencing company access to its own history -- which reaches the user as
     a bare "Access Error" on login with no clue what caused it. This must
     happen BEFORE anything else, not as a repair afterwards.
  2. Source stock is zeroed BEFORE the originals are archived, because an
     inventory adjustment cannot be applied to an archived product.
  3. Source stock is zeroed AT ALL, because otherwise the same physical goods
     are counted in two companies and the parent keeps stock value on its
     balance sheet for things it can no longer sell.
  4. Every write is re-read and verified. An earlier version of this script
     reported "moved" for records that had not moved.

Run with:
    venv/Scripts/python.exe odoo/odoo-bin shell -c odoo.conf -d <db> --no-http \
        < custom_addons/pos_retail/scripts/copy_catalogue_to_branch.py
"""

SOURCE_COMPANY_ID = 1
TARGET_COMPANY_ID = 3
DRY_RUN = True

src = env['res.company'].sudo().browse(SOURCE_COMPANY_ID)
dst = env['res.company'].sudo().browse(TARGET_COMPANY_ID)

Template = env['product.template'].sudo()
Quant = env['stock.quant'].sudo()
Warehouse = env['stock.warehouse'].sudo()
Partner = env['res.partner'].sudo()

problems = []


def verify(label, condition, detail=""):
    """Assert a step actually happened. Silence is not success."""
    if condition:
        print("    verified: %s %s" % (label, detail))
    else:
        problems.append("%s %s" % (label, detail))
        print("    *** NOT VERIFIED: %s %s" % (label, detail))


print("=" * 76)
print("CATALOGUE MIGRATION  %s -> %s   %s"
      % (src.name, dst.name, "(DRY RUN)" if DRY_RUN else "(WRITING)"))
print("=" * 76)

if src == dst or not src or not dst:
    raise UserError("Source and target must be two different existing companies.")
if dst.parent_id != src and src.parent_id != dst:
    print("  NOTE: %s is not a branch of %s. Continuing anyway." % (dst.name, src.name))

# --- 0. protect partners used by more than one company -----------------------
print("\n[0] Partners referenced across company boundaries")
owned = Partner.search([('company_id', '!=', False)])
candidates = Partner.search([('company_id', '=', src.id)])
at_risk = Partner.browse()
for model, fields in [('purchase.order', ['partner_id']),
                      ('sale.order', ['partner_id', 'partner_invoice_id', 'partner_shipping_id']),
                      ('pos.order', ['partner_id']),
                      ('account.move', ['partner_id']),
                      ('stock.picking', ['partner_id']),
                      ('account.payment', ['partner_id'])]:
    if model not in env:
        continue
    M = env[model].sudo()
    for f in fields:
        if f not in M._fields:
            continue
        for rec in M.search([(f, 'in', (owned | candidates).ids)]):
            p = rec[f]
            # Referenced by a company that will not own it after the move.
            if p and rec.company_id and rec.company_id != dst:
                if p in candidates or (p.company_id and p.company_id != rec.company_id):
                    at_risk |= p
print("    partners that must stay SHARED: %s" % len(at_risk))
for p in at_risk[:10]:
    print("      %s" % p.name)
if not DRY_RUN and at_risk:
    at_risk.write({'company_id': False})
    at_risk.invalidate_recordset()
    verify("shared", all(not p.company_id for p in at_risk), "(%s partners)" % len(at_risk))

# --- 1. somewhere for the branch to hold stock -------------------------------
print("\n[1] Branch warehouse")
wh = Warehouse.search([('company_id', '=', dst.id)], limit=1)
if wh:
    print("    exists: %s" % wh.name)
elif not DRY_RUN:
    wh = Warehouse.create({
        'name': "%s Warehouse" % dst.name,
        'code': ("B%s" % dst.id)[:5],   # prefixes every picking sequence
        'company_id': dst.id,
        'partner_id': dst.partner_id.id,
    })
    verify("warehouse created", bool(wh.lot_stock_id), wh.name)
else:
    print("    would be created")

# --- 2. copy the catalogue ---------------------------------------------------
print("\n[2] Catalogue")
templates = Template.search([('company_id', '=', src.id)])
stock_by_tmpl = {}
for tmpl in templates:
    qty = sum(Quant.search([
        ('product_id', 'in', tmpl.product_variant_ids.ids),
        ('location_id.usage', '=', 'internal'),
        ('company_id', '=', src.id),
    ]).mapped('quantity'))
    if qty:
        stock_by_tmpl[tmpl.id] = qty
print("    products: %s   holding stock: %s (%s units)"
      % (len(templates), len(stock_by_tmpl), int(sum(stock_by_tmpl.values()))))

copied, failed = [], []
if not DRY_RUN:
    for tmpl in templates:
        try:
            # Both records are company-scoped and a barcode need only be unique
            # WITHIN a company, so the copy may carry the same barcode. That is
            # the point: one printed label scans in either shop.
            new = tmpl.with_company(dst).copy({
                'name': tmpl.name,
                'company_id': dst.id,
                'default_code': tmpl.default_code,
                'barcode': tmpl.barcode,
                'active': True,
            })
            copied.append((tmpl, new))
        except Exception as exc:
            failed.append((tmpl.display_name, str(exc)[:90]))
    verify("copied", len(copied) == len(templates),
           "%s of %s (%s failed)" % (len(copied), len(templates), len(failed)))
    for name, err in failed[:5]:
        print("      FAILED %s -> %s" % (name[:38], err))

    # --- 3. count the stock in at the branch ---------------------------------
    placed = 0
    for old, new in copied:
        qty = stock_by_tmpl.get(old.id)
        if not qty:
            continue
        q = Quant.with_company(dst).with_context(inventory_mode=True).create({
            'product_id': new.product_variant_id.id,
            'location_id': wh.lot_stock_id.id,
            'inventory_quantity': qty,
        })
        q.action_apply_inventory()
        placed += 1
    dst_units = sum(Quant.search([('company_id', '=', dst.id),
                                  ('location_id.usage', '=', 'internal')]).mapped('quantity'))
    verify("stock counted in", placed == len(stock_by_tmpl),
           "%s products, %s units at %s" % (placed, int(dst_units), wh.lot_stock_id.complete_name))

    # --- 4. zero the source, BEFORE archiving --------------------------------
    # An inventory adjustment cannot be applied to an archived product, and
    # leaving the stock behind would count the same goods twice.
    src_quants = Quant.search([('company_id', '=', src.id),
                               ('location_id.usage', '=', 'internal'),
                               ('quantity', '!=', 0)])
    for q in src_quants:
        q.with_context(inventory_mode=True).inventory_quantity = 0
    if src_quants:
        src_quants.with_context(inventory_mode=True).action_apply_inventory()
    left = sum(Quant.search([('company_id', '=', src.id),
                             ('location_id.usage', '=', 'internal')]).mapped('quantity'))
    verify("source stock cleared", abs(left) < 0.001, "%s units left on %s" % (int(left), src.name))

    # --- 5. retire the originals ---------------------------------------------
    templates.write({'active': False})
    templates.invalidate_recordset()
    still_active = Template.search_count([('company_id', '=', src.id)])
    verify("originals archived", still_active == 0, "%s still active" % still_active)

# --- 6. contacts and expenses ------------------------------------------------
print("\n[3] Contacts and expenses")
all_partners = Partner.search([('company_id', '=', src.id)])
# Internal contacts stay put: res_partner.py:894 refuses to move the partner
# behind a user into a company that user is not a member of, and they are
# exempt from the branch rule anyway (partner_share=False).
movable = all_partners.filtered(lambda p: p.partner_share and not p.user_ids)
staying = all_partners - movable
print("    move: %s    stay: %s (%s)"
      % (len(movable), len(staying), ", ".join(staying.mapped('name')[:4]) or "none"))
expenses = env['pos.retail.expense'].sudo().search([('company_id', '=', src.id)]) \
    if 'pos.retail.expense' in env else env['res.partner'].browse()
print("    expenses: %s" % len(expenses))
if not DRY_RUN:
    if movable:
        movable.write({'company_id': dst.id})
        movable.invalidate_recordset()
        verify("contacts moved", all(p.company_id == dst for p in movable), "(%s)" % len(movable))
    if expenses:
        expenses.write({'company_id': dst.id})
        expenses.invalidate_recordset()
        verify("expenses moved", all(x.company_id == dst for x in expenses), "(%s)" % len(expenses))

# --- 7. left behind, deliberately --------------------------------------------
print("\n[4] Left with the parent, deliberately")
print("    %s POS orders, %s journal entries -- posted history"
      % (env['pos.order'].sudo().search_count([('company_id', '=', src.id)]),
         env['account.move'].sudo().search_count([('company_id', '=', src.id)])))
print("    %s active register(s) -- retire only once the branch has one"
      % env['pos.config'].sudo().search_count([('company_id', '=', src.id), ('active', '=', True)]))

print("\n" + "=" * 76)
if DRY_RUN:
    env.cr.rollback()
    print("DRY RUN complete, nothing written. Set DRY_RUN = False to apply.")
elif problems:
    env.cr.rollback()
    print("ROLLED BACK -- %s step(s) could not be verified:" % len(problems))
    for p in problems:
        print("  - %s" % p)
else:
    env.cr.commit()
    print("Committed, every step verified.")
print("=" * 76)
