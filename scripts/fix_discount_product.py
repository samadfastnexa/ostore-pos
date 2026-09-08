"""Give every register the discount product its discount buttons need.

    venv/Scripts/python.exe odoo/odoo-bin shell -c odoo.conf -d <db> --no-http \
        < custom_addons/pos_retail/scripts/fix_discount_product.py

On the server:
    sudo -u odoo /opt/odoo/venv/bin/python3 /opt/odoo/odoo/odoo-bin shell \
        -c /etc/odoo/odoo.conf -d ostore_live --no-http \
        < /opt/odoo/custom_addons/pos_retail/scripts/fix_discount_product.py

Fixes this, seen at a live till: pressing "Discount the rest" pops
"The discount product seems misconfigured" and nothing is discounted.

A discount is rung up as a line on a product, so a register with no
discount_product_id set has nothing to write the discount onto. The product
itself is not usually missing -- pos_discount ships one, shared across every
company -- it simply was never attached to the register. A register created
by commission_branch.py had exactly that gap, so this affects new branches
rather than being a one-off.

Note what "misconfigured" does NOT mean here. On a working database the
product has available_in_pos = False and discounts are fine: POS loads the
discount product because the register points at it, not because it appears
in the catalogue. Chasing those flags is a dead end; the field being empty
is the whole problem.

READ ONLY until APPLY is set to True.
"""

APPLY = False

Config = env['pos.config'].sudo().with_context(active_test=False)
Product = env['product.product'].sudo()

shipped = env.ref('pos_discount.product_product_consumable', raise_if_not_found=False)

missing, present = [], []
for config in Config.search([]):
    (present if config.discount_product_id else missing).append(config)

print()
print("=" * 78)
print("DISCOUNT PRODUCT" + ("" if APPLY else "   (DRY RUN -- nothing written)"))
print("=" * 78)

for config in present:
    product = config.discount_product_id
    print("  [SET]  %-28s uses %r (company: %s)"
          % (config.name, product.display_name, product.company_id.name or 'shared'))

    # Having the field filled in is NOT the same as the till being able to use
    # it, and an earlier version of this script stopped at the field and
    # printed [OK] -- which sent a live shop looking in the wrong place while
    # the register kept refusing discounts. The till resolves
    # config.discount_product_id against the products it was SENT, so the only
    # answer that settles anything is whether the product is in that payload.
    print("      active=%s  sale_ok=%s  available_in_pos=%s"
          % (product.active, product.sale_ok, product.available_in_pos))
    print("      (available_in_pos False is normal -- a working shop has it off;"
          " the product travels as a 'special product', not as catalogue)")

    specials = config._get_special_products()
    in_specials = product in specials
    survives = product in specials.filtered(
        lambda p: not p.sudo().company_id or p.sudo().company_id == env.company)
    print("      listed as a special product: %s" % in_specials)
    print("      survives the company filter: %s   (env.company=%r)"
          % (survives, env.company.name))

    session = env['pos.session'].sudo().search(
        [('config_id', '=', config.id)], order='id desc', limit=1)
    if not session:
        print("      no session ever opened here, so the loader cannot be run")
        continue
    try:
        # empty list loads every model: product.template's loader reads
        # data['pos.config'], so it cannot be fetched on its own
        payload = session.load_data([])
        tmpl_ids = {row['id'] for row in payload.get('product.template', [])}
        reached = product.product_tmpl_id.id in tmpl_ids
        print("      IN THE TILL'S PAYLOAD: %s   (%s products sent)"
              % ("YES" if reached else "NO -- this is the fault", len(tmpl_ids)))
    except Exception as exc:
        print("      loader could not run here: %s" % str(exc)[:110])

if not missing:
    print("  every register already has one -- nothing to do")
else:
    if not shipped:
        print("  Cannot repair: the product pos_discount ships is not in this")
        print("  database. Set a discount product by hand on each register under")
        print("  Point of Sale > Configuration > Settings.")
    else:
        # sale_ok and active matter (an archived or unsellable product cannot be
        # put on an order line); available_in_pos deliberately does not.
        repairs = {}
        if not shipped.sale_ok:
            repairs['sale_ok'] = True
        if not shipped.active:
            repairs['active'] = True

        for config in missing:
            print("  [FIX]  %-28s has none; would use %r"
                  % (config.name, shipped.display_name))
        if repairs:
            print("  the product also needs: %s" % repairs)

        if APPLY:
            if repairs:
                shipped.write(repairs)
            for config in missing:
                config.discount_product_id = shipped.id
            env.cr.commit()
            print()
            print("Fixed %s register(s). Reload the till (close and reopen the browser"
                  % len(missing))
            print("tab) -- the register's settings are cached in the running session.")

if not APPLY and missing:
    print()
    print("=" * 78)
    print("Nothing was written. Set APPLY = True near the top, or pipe it:")
    print("  sed 's/^APPLY = False/APPLY = True/' <this file> | odoo-bin shell ...")
    print("=" * 78)
