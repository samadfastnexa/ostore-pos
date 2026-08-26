"""Give every branch its own product records instead of one shared catalogue.

Each currently-shared product ends up as TWO records: the original keeps the
company that holds its history, and a copy is created for the other branch.
Stock follows the record for its own branch.

Deliberately left shared: the POS special products (Tips, Discount). They are
referenced by every register, and scoping them to one company breaks the other.

Set LIMIT to a small number for a rehearsal; None migrates everything.
"""
LIMIT = None

T = env['product.template'].sudo()
Q = env['stock.quant'].sudo()
Line = env['pos.order.line'].sudo()

MAIN = env['res.company'].sudo().browse(1)     # Cash & Carry (parent)
BRANCH = env['res.company'].sudo().browse(2)   # Cusotmer 1

# Only products actually sold at a till. Everything else shared is plumbing --
# Tips, Discount, Down Payment, Gift Card, eWallet top-ups -- and every register
# resolves those through its own config, so scoping them to one company breaks
# the other branch.
special = env['pos.config'].sudo().search([])._get_special_products().product_tmpl_id
targets = T.search([('company_id', '=', False), ('available_in_pos', '=', True)]) - special
if LIMIT:
    targets = targets[:LIMIT]
print(f"migrating {len(targets)} products; leaving {len(special)} special products shared")

def company_holding_history(tmpl):
    """The branch whose orders reference this product keeps the original record."""
    lines = Line.search([('product_id', 'in', tmpl.product_variant_ids.ids)], limit=50)
    comps = lines.mapped('order_id.company_id')
    return comps[0] if comps else MAIN

done = failed = 0
for tmpl in targets:
    try:
        owner = company_holding_history(tmpl)
        other = BRANCH if owner == MAIN else MAIN

        # 1. The copy for the other branch. copy() clears barcode/default_code
        #    to avoid duplicates inside one company; across companies they are
        #    allowed (product_product.py:286) and the same physical item must
        #    scan identically in both shops, so put them back.
        copy = tmpl.copy({'name': tmpl.name, 'company_id': other.id})
        for old_v, new_v in zip(tmpl.product_variant_ids, copy.product_variant_ids):
            # standard_price is company-dependent, so it does not travel with copy()
            new_v.with_company(other).standard_price = old_v.with_company(owner).standard_price

        # 2. Move the other branch's stock onto its own record BEFORE the
        #    original changes owner - a quant in company B on a product owned by
        #    company A fails Odoo's company-consistency check.
        moved = 0
        for old_v, new_v in zip(tmpl.product_variant_ids, copy.product_variant_ids):
            quants = Q.search([
                ('product_id', '=', old_v.id),
                ('company_id', '=', other.id),
            ])
            for q in quants:
                qty, loc = q.quantity, q.location_id
                q.with_context(inventory_mode=True).unlink()
                if qty:
                    Q.create({'product_id': new_v.id, 'location_id': loc.id, 'quantity': qty})
                    moved += 1

        # 3. Now the original can be scoped to the branch that owns its history.
        tmpl.company_id = owner.id

        # 4. Identifying codes LAST, and only once both records are scoped.
        #    Barcodes are unique per company (product_product.py:283-290), but a
        #    SHARED product sits in every company's namespace at once -- so while
        #    the original is still shared, giving the copy the same barcode
        #    collides with it. After step 3 the two live in different companies
        #    and the same physical item can scan identically in both shops.
        #    Overwrite rather than fill-if-empty: pos_retail's auto-barcode hook
        #    has already minted a throwaway code for the copy by now.
        for old_v, new_v in zip(tmpl.product_variant_ids, copy.product_variant_ids):
            vals = {}
            if old_v.barcode:
                vals['barcode'] = old_v.barcode
            if old_v.default_code:
                vals['default_code'] = old_v.default_code
            if vals:
                new_v.write(vals)

        env.cr.commit()
        done += 1
        if done % 25 == 0:
            print(f"  ... {done} migrated")
    except Exception as e:
        env.cr.rollback()
        failed += 1
        print(f"  FAIL '{tmpl.name}': {str(e)[:150]}")

print(f"\nmigrated={done} failed={failed}")
