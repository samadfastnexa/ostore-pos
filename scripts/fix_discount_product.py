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
    print("  [OK]   %-28s uses %r (company: %s)"
          % (config.name, product.display_name, product.company_id.name or 'shared'))

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
