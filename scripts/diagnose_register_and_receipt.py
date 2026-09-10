"""Answer three separate complaints with measurements, not guesses.

    sudo -u odoo /opt/odoo/venv/bin/python3 /opt/odoo/odoo/odoo-bin shell \
        -c /etc/odoo/odoo.conf -d ostore_live --no-http \
        < /opt/odoo/custom_addons/pos_retail/scripts/diagnose_register_and_receipt.py

Reads only. Writes nothing, under any circumstances, so it is safe to run on
a trading day.

  A. The parent company still offers a register on the dashboard, after it
     was supposed to have been retired. Either the retirement did not take,
     or a second register exists that nobody retired. Those need different
     fixes, so this says which.

  B. "PDF is not showing". Odoo builds PDFs with an external binary. When
     that binary is absent Odoo does not fail loudly -- the web client asks
     /report/check_wkhtmltopdf first and quietly serves the report as a web
     page instead, which is why a receipt arrives as plain text with no
     layout. This reports the binary's state directly.

  C. A receipt printed "0 x" against a line that still charged money. A
     quantity of zero costing 230 is a contradiction, so one of the two is
     being displayed wrong. The client formats quantity through the "Product
     Unit" decimal precision: a fractional quantity shown with too few
     decimals reads as 0. This prints the stored quantity at full precision
     next to what the receipt would render, so the two can be compared.
"""

# The receipt in question. Change to look at a different one.
RECEIPT_REF = '261-2-000006'

PosConfig = env['pos.config'].sudo()
PosOrder = env['pos.order'].sudo()
Company = env['res.company'].sudo()
Report = env['ir.actions.report'].sudo()
DP = env['decimal.precision'].sudo()

line_break = "=" * 78

print()
print(line_break)
print("A. REGISTERS, PER COMPANY")
print(line_break)

# active_test=False so an archived register is still listed. A register that
# was archived but keeps appearing means something else is wrong, and that is
# worth telling apart from one that was never archived at all.
for company in Company.search([]):
    configs = PosConfig.with_context(active_test=False).search(
        [('company_id', '=', company.id)])
    print()
    print("  %r  (id %s%s)" % (
        company.name, company.id,
        ", branch of %r" % company.parent_id.name if company.parent_id else ", parent"))
    if not configs:
        print("      no register")
        continue
    for config in configs:
        orders = PosOrder.search_count([('config_id', '=', config.id)])
        session = config.current_session_id
        print("      %-24r active=%-5s orders=%-5s open session=%s" % (
            config.name[:22], config.active, orders,
            session.name if session else "none"))

print()
print("  A register shows on the dashboard when active is True. If the parent's")
print("  register reads active=True, the retirement did not take. If it reads")
print("  active=False and a card still appears, the card belongs to a DIFFERENT")
print("  register listed above.")

print()
print(line_break)
print("B. PDF ENGINE")
print(line_break)

state = Report.get_wkhtmltopdf_state()
print()
print("  wkhtmltopdf state: %r" % state)
meaning = {
    'install': "NOT INSTALLED. This is the whole cause: Odoo serves reports as a\n"
               "      web page instead of a PDF, which is why the receipt arrives as\n"
               "      unformatted text.",
    'ok': "installed and usable. If a PDF still will not appear the cause is\n"
          "      elsewhere, most likely the browser blocking the popup or the report\n"
          "      raising on this particular record.",
    'upgrade': "installed but too old to render headers and footers. Receipts will\n"
               "      print, but page chrome will be wrong.",
    'workers': "installed, but this server runs a single worker, so it cannot call\n"
               "      itself to render. Needs workers = 2 or more in the config.",
    'broken': "installed but failing to run. Usually a missing system library.",
}
print("      %s" % meaning.get(state, "unrecognised state"))

print()
print("  Receipt reports registered by this module:")
for report in Report.search([('report_name', 'like', 'pos_retail')]):
    print("      %-46r type=%s" % (report.report_name, report.report_type))

print()
print(line_break)
print("C. THE RECEIPT THAT PRINTED '0 x'")
print(line_break)

order = PosOrder.search([('pos_reference', 'like', RECEIPT_REF)], limit=1)
if not order:
    order = PosOrder.search([('name', 'like', RECEIPT_REF)], limit=1)

if not order:
    print()
    print("  No order found for %r. Change RECEIPT_REF at the top of this file." % RECEIPT_REF)
else:
    digits = DP.precision_get('Product Unit')
    print()
    print("  Order %r on register %r, company %r" % (
        order.pos_reference or order.name, order.config_id.name, order.company_id.name))
    print("  'Product Unit' decimal precision: %s digit(s)" % digits)
    print()
    for line in order.lines:
        unit = line.product_id.uom_id
        # repr on the raw float on purpose. A quantity that reads 0 on the
        # receipt but is really 0.5 is the entire question here, and any
        # rounding applied while printing this would hide the answer.
        print("      %-30r" % (line.full_product_name or line.product_id.display_name)[:28])
        print("          qty stored      : %r" % line.qty)
        print("          qty as printed  : %s" % (
            ("%%.%df" % digits) % line.qty if digits else "%.0f" % line.qty))
        print("          unit price      : %r" % line.price_unit)
        print("          line total      : %r" % line.price_subtotal_incl)
        print("          unit of measure : %r  rounding=%r" % (
            unit.name, unit.rounding))
        print("          discount %%       : %r" % line.discount)
    print()
    print("      ORDER TOTAL: %r" % order.amount_total)
    print()
    print("  If 'qty stored' is a fraction and 'qty as printed' is 0, the sale is")
    print("  correct and only the display is wrong: raise the 'Product Unit'")
    print("  precision. If 'qty stored' really is 0 while the line charged money,")
    print("  the sale itself is wrong and the cause is upstream of the receipt.")

print()
print(line_break)
print("Nothing was written.")
print(line_break)
