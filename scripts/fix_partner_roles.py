"""Take vendors out of the Customers list when they were never sold to.

    venv/Scripts/python.exe odoo/odoo-bin shell -c odoo.conf -d <db> --no-http \
        < custom_addons/pos_retail/scripts/fix_partner_roles.py

On the server:
    sudo -u odoo /opt/odoo/venv/bin/python3 /opt/odoo/odoo/odoo-bin shell \
        -c /etc/odoo/odoo.conf -d ostore_live --no-http \
        < /opt/odoo/custom_addons/pos_retail/scripts/fix_partner_roles.py

The Customers menu already filters on customer_rank > 0, so a vendor showing
up there is not a filtering fault: that partner really does carry a customer
flag. Usually because it was created while the Customers screen was open --
that screen sets customer_rank to 1 on anything new, which is right for a
customer and wrong for a supplier typed in from the same place.

DECIDED FROM HISTORY, NOT FROM THE FLAG. A partner is only un-flagged when
BOTH are true:

  * nothing was ever sold to them -- no POS order, no sales order, no
    customer invoice, and
  * something WAS bought from them -- a purchase order or a vendor bill

A partner you genuinely both buy from and sell to keeps both flags: that is a
real arrangement in this trade, not a mistake, and this must not quietly
break it. A partner with no history either way is also left alone, since
nothing here says what they are.

READ ONLY until APPLY is set to True.
"""

APPLY = False

Partner = env['res.partner'].sudo()
PO = env['purchase.order'].sudo()
SO = env['sale.order'].sudo()
PosOrder = env['pos.order'].sudo()
Move = env['account.move'].sudo()


def sold_to(partner):
    return (PosOrder.search_count([('partner_id', '=', partner.id)])
            + SO.search_count([('partner_id', '=', partner.id)])
            + Move.search_count([('partner_id', '=', partner.id),
                                 ('move_type', 'in', ('out_invoice', 'out_refund'))]))


def bought_from(partner):
    return (PO.search_count([('partner_id', '=', partner.id)])
            + Move.search_count([('partner_id', '=', partner.id),
                                 ('move_type', 'in', ('in_invoice', 'in_refund'))]))


flagged = Partner.search([('customer_rank', '>', 0)])
to_clear, genuine_both, no_history = [], [], []

for partner in flagged:
    sales = sold_to(partner)
    buys = bought_from(partner)
    if sales:
        if buys:
            genuine_both.append((partner, sales, buys))
        continue
    if buys:
        to_clear.append((partner, buys))
    else:
        no_history.append(partner)

print()
print("=" * 78)
print("CUSTOMER / VENDOR FLAGS" + ("" if APPLY else "   (DRY RUN -- nothing written)"))
print("=" * 78)
print("  %s partner(s) currently appear under Customers" % len(flagged))

if to_clear:
    print()
    print("  Bought from, never sold to -- these are vendors in the wrong list:")
    for partner, buys in to_clear:
        print("      %-32r %s purchase document(s)" % (partner.name[:30], buys))

if genuine_both:
    print()
    print("  Genuinely both, KEPT in Customers (real sales AND real purchases):")
    for partner, sales, buys in genuine_both:
        print("      %-32r sales=%-4s purchases=%s" % (partner.name[:30], sales, buys))

if no_history:
    print()
    print("  No history either way, LEFT ALONE (%s): nothing here says what they" % len(no_history))
    print("  are, and guessing would be worse than leaving them where the shop put them.")

if APPLY and to_clear:
    for partner, _buys in to_clear:
        partner.customer_rank = 0
    env.cr.commit()
    print()
    print("Cleared the customer flag on %s vendor(s). They stay under Vendors and" % len(to_clear))
    print("keep every document they are on; only the Customers list changes.")
elif to_clear:
    print()
    print("=" * 78)
    print("Nothing was written. Set APPLY = True to clear those, or pipe it:")
    print("  sed 's/^APPLY = False/APPLY = True/' <this file> | odoo-bin shell ...")
    print("=" * 78)
elif not to_clear:
    print()
    print("Nothing to correct.")
