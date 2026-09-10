"""Take the parent's empty register off the dashboard, and expose a second
register that is sitting on the wrong company.

    sudo -u odoo /opt/odoo/venv/bin/python3 /opt/odoo/odoo/odoo-bin shell \
        -c /etc/odoo/odoo.conf -d ostore_live --no-http \
        < /opt/odoo/custom_addons/pos_retail/scripts/fix_stray_registers.py

WHAT THE DIAGNOSTIC FOUND.

  Murshid Company (parent)  register, archived, 16 orders   <- retired, correct
  Murshid Company (parent)  register, ACTIVE,    0 orders   <- the card on screen
  Murshad Bahria Branch     'Murshid Bahria Branch', 41 orders
  Murshad Bahria Branch     'murshid uthal',          0 orders   <- WRONG COMPANY
  murshid uthal             no register at all

So the earlier retirement did work. A second, empty register was created on
the parent afterwards, and that is what still shows. This archives it.

THE SECOND PROBLEM IS NOT TOUCHED, ON PURPOSE. A register named after Uthal
belongs to the Bahria company. That is not cosmetic: a register's company
decides which stock is sold, which journal takes the money and which till
the cash lands in. Every sale rung up on it would be a Bahria sale wearing
Uthal's name, and the two branches own their books separately.

It has no orders yet, so nothing is wrong in the accounts today. But it
cannot simply be pointed at the Uthal company either -- a register's
journals, payment methods, stock picking type and pricelist must all belong
to the same company, and Uthal has none of its own yet. Moving the company
field alone would fail on those constraints, or worse, half-succeed.

So this reports exactly what Uthal is missing and leaves the decision alone.
Commissioning a branch properly is what commission_branch.py is for.

READ ONLY until APPLY is set to True.
"""

APPLY = False

PosConfig = env['pos.config'].sudo()
PosOrder = env['pos.order'].sudo()
Company = env['res.company'].sudo()
Journal = env['account.journal'].sudo()
Product = env['product.product'].sudo()

line_break = "=" * 78

print()
print(line_break)
print("STRAY REGISTERS" + ("" if APPLY else "   (DRY RUN -- nothing written)"))
print(line_break)

# A register is only ever archived here when all three are true: it belongs
# to a parent company, it has never taken an order, and no session is open on
# it. Anything that has traded keeps its register, because the orders,
# sessions and journal entries all hang off it and archiving is how history
# is kept readable rather than deleted.
parents = Company.search([('parent_id', '=', False)])
candidates = PosConfig.search([('company_id', 'in', parents.ids), ('active', '=', True)])

safe, unsafe = [], []
for config in candidates:
    orders = PosOrder.search_count([('config_id', '=', config.id)])
    if orders or config.current_session_id:
        unsafe.append((config, orders))
    else:
        safe.append(config)

print()
print("  Active registers on a parent company:")
if not candidates:
    print("      none -- nothing to do")
for config in safe:
    print("      %-26r 0 orders, no open session  -> SAFE TO ARCHIVE" % config.name[:24])
for config, orders in unsafe:
    print("      %-26r %s order(s)%s  -> LEFT ALONE, it has traded" % (
        config.name[:24], orders,
        ", session OPEN" if config.current_session_id else ""))

if APPLY and safe:
    for config in safe:
        config.active = False
    env.cr.commit()
    print()
    print("  Archived %s register(s). The card disappears from the dashboard;" % len(safe))
    print("  nothing is deleted and it can be un-archived if that was wrong.")

print()
print(line_break)
print("REGISTERS ON THE WRONG COMPANY")
print(line_break)

# A register whose name matches one company while it belongs to another is
# the signature of this mistake: it was created while the wrong company was
# active in the switcher, which stamps the company silently.
suspects = []
for config in PosConfig.search([]):
    named_for = Company.search([('name', '=ilike', config.name.strip())], limit=1)
    if named_for and named_for != config.company_id:
        suspects.append((config, named_for))

if not suspects:
    print()
    print("  None found.")
else:
    for config, named_for in suspects:
        orders = PosOrder.search_count([('config_id', '=', config.id)])
        print()
        print("  Register %r" % config.name)
        print("      belongs to : %r" % config.company_id.name)
        print("      named after: %r" % named_for.name)
        print("      orders     : %s" % orders)
        print()
        print("      What %r would need before this register could move to it:" % named_for.name)
        products = Product.search_count([('company_id', '=', named_for.id)])
        sale_journals = Journal.search_count(
            [('company_id', '=', named_for.id), ('type', '=', 'sale')])
        cash_journals = Journal.search_count(
            [('company_id', '=', named_for.id), ('type', '=', 'cash')])
        # Products with no company are shared across the whole tree, which is
        # how this shop's catalogue is arranged, so a zero here is not
        # automatically a blocker. Reported plainly rather than judged.
        shared_products = Product.search_count([('company_id', '=', False)])
        print("          own products        : %s   (plus %s shared across all companies)"
              % (products, shared_products))
        print("          own sales journal   : %s" % sale_journals)
        print("          own cash journal    : %s" % cash_journals)
        print()
        print("      Not changed by this script. Moving a register's company while")
        print("      its journals and stock still belong to another company is how")
        print("      money ends up in the wrong branch's books.")

print()
print(line_break)
if not APPLY and safe:
    print("Nothing was written. Set APPLY = True, or pipe it:")
    print("  sed 's/^APPLY = False/APPLY = True/' <this file> | odoo-bin shell ...")
else:
    print("Nothing was written." if not APPLY else "Done.")
print(line_break)
