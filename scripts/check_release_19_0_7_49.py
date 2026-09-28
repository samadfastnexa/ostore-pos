"""Verify the 19.0.7.49.0 release on any database. READ ONLY.

Safe to run against production: everything it touches is rolled back at the
end, and the product it tries labels on is only ever read or held in memory.
Run it right after the upgrade, before anyone opens a till.

    venv/Scripts/python.exe odoo/odoo-bin shell -c odoo.conf -d <db> --no-http \
        < custom_addons/pos_retail/scripts/check_release_19_0_7_49.py

On the server:
    sudo -u odoo /opt/odoo/venv/bin/python3 /opt/odoo/odoo/odoo-bin shell \
        -c /etc/odoo/odoo.conf -d ostore_live --no-http \
        < /opt/odoo/custom_addons/pos_retail/scripts/check_release_19_0_7_49.py

What it covers, one section per change in the release:
  TILL          category colours on product cards, "All" paging past 100
  BACK OFFICE   product name and barcode in separate columns
  QUOTATIONS    no product code on quotation lines, old ones cleaned
  ROUND TRIP    Back Office -> Back to Till keeps the login and cashier
The till checks read the compiled POS bundle, i.e. what browsers will be
served, not the source files.
"""
import inspect

EXPECTED_VERSION = '19.0.7.49.0'
KEY = 'pos_retail_hide_product_code'

results = []


def check(name, ok, detail="", severity="FAIL"):
    results.append((name, bool(ok), detail, severity))
    print("  [%-4s] %-50s %s" % ("PASS" if ok else severity, name, detail))


print("=" * 78)
print("RELEASE %s CHECK   db=%s" % (EXPECTED_VERSION, env.cr.dbname))
print("=" * 78)

# ---------------------------------------------------------------- module
print("\nMODULE")
mod = env['ir.module.module'].sudo().search([('name', '=', 'pos_retail')])
check("pos_retail installed at %s" % EXPECTED_VERSION,
      mod.state == 'installed' and mod.latest_version == EXPECTED_VERSION,
      "%s / %s" % (mod.state, mod.latest_version))

# ---------------------------------------------------------------- till
print("\nTILL (compiled POS bundle, what browsers get)")
try:
    bundle = env['ir.qweb']._get_asset_bundle('point_of_sale.assets_prod', css=True, js=True)
    js = bundle.js().raw.decode('utf-8', 'ignore')
    css = "".join(a.raw.decode('utf-8', 'ignore') for a in bundle.css())
    check("product cards tinted by category colour",
          'var(--bg) 65%' in css and 'o_colorlist_item_color_transparent_' in css)
    check("'All' grid pages past 100 products", 'posRetailGrowGridNearBottom' in js)
    check("Back Office keeps the signed-in cashier",
          'startsWith("connected_cashier_")' in js or "startsWith('connected_cashier_')" in js)
    check("Direct Login keeps a PIN-signed cashier", '_getConnectedCashier?.()' in js)
except Exception as e:
    check("POS bundle compiles", False, "%s: %s" % (type(e).__name__, e))

Categ = env['pos.category'].sudo()
uncoloured = Categ.search([('color', '=', 0)])
check("every till category has a colour", not uncoloured,
      ", ".join(uncoloured.mapped('name')) + (" -> plain white cards" if uncoloured else ""),
      severity="WARN")
for c in Categ.search([('parent_id', '=', False)], order='sequence'):
    print("         %-28s colour %s" % (c.name[:28], c.color))

# ---------------------------------------------------------------- back office
print("\nBACK OFFICE (product name and barcode in separate columns)")
models_with_column = [
    'stock.quant', 'stock.scrap', 'stock.move', 'pos.order.line',
    'pos.retail.line.discount.log', 'pos.retail.customer.refund.item',
    'pos.retail.vendor.return.item', 'pos.retail.customer.refund.line',
    'pos.retail.vendor.refund.line',
]
missing = [m for m in models_with_column
           if 'pos_retail_product_barcode' not in env[m]._fields]
check("Barcode field on all %s models" % len(models_with_column), not missing,
      ", ".join(missing))

product = env['product.product'].sudo().search(
    [('default_code', '!=', False), ('sale_ok', '=', True)], limit=1)
if product:
    code = product.default_code
    plain = product.with_context(**{KEY: True}).display_name
    default = product.display_name
    dropdown = product.with_context(**{KEY: True, 'formatted_display_name': True}).display_name
    check("our screens: name without code", not plain.startswith("[%s]" % code), repr(plain))
    check("elsewhere: Odoo's label unchanged", default.startswith("[%s]" % code), repr(default))
    check("dropdowns still show the code", code in dropdown, repr(dropdown))
else:
    check("a product with an internal reference to test on", False,
          "none found; label checks skipped", severity="WARN")

Action = env['ir.actions.act_window'].sudo()
with_key = Action.search([('context', 'like', KEY)])
check("screens carrying the name-only switch", len(with_key) >= 48,
      "%s actions (expected 48)" % len(with_key))
for xmlid in ('point_of_sale.action_pos_pos_form', 'point_of_sale.action_report_pos_order_all',
              'pos_retail.action_pos_retail_record_damage',
              'pos_retail.action_pos_retail_quotations'):
    act = env.ref(xmlid, raise_if_not_found=False)
    check("  %s" % xmlid.split('.')[1], act and KEY in (act.context or ''))

views = [
    ('pos_retail.view_stock_quant_list_pos_retail_count', 'list'),
    ('pos_retail.view_stock_scrap_list_pos_retail', 'list'),
    ('pos_retail.pos_retail_price_report_list', 'list'),
    ('pos_retail.pos_retail_package_sales_view_list', 'list'),
    ('pos_retail.pos_retail_line_discount_log_view_list', 'list'),
    ('pos_retail.pos_retail_customer_refund_line_list', 'list'),
    ('pos_retail.pos_retail_vendor_refund_line_list', 'list'),
    ('pos_retail.view_picking_form_pos_retail_reception', 'form'),
    ('point_of_sale.view_pos_pos_form', 'form'),
    ('pos_retail.pos_retail_customer_refund_view_form', 'form'),
    ('pos_retail.pos_retail_vendor_return_view_form', 'form'),
]
no_column = []
for xmlid, kind in views:
    view = env.ref(xmlid)
    arch = env[view.model].sudo().get_view(view.id, kind)['arch']
    if 'pos_retail_product_barcode' not in arch:
        no_column.append(xmlid.split('.')[1])
movement = env.ref('pos_retail.pos_retail_inventory_movement_view_list')
if 'name="barcode" optional="show"' not in movement.arch_db:
    no_column.append('inventory movements (barcode shown)')
check("Barcode column on %s screens" % (len(views) + 1), not no_column, ", ".join(no_column))
count_arch = env.ref('pos_retail.view_stock_quant_list_pos_retail_count').arch_db
check("Stock Count: switch on the field, not the action", KEY in count_arch)

# ---------------------------------------------------------------- quotations
print("\nQUOTATIONS (no product code on lines)")
Line = env['sale.order.line'].sudo()
open_lines = Line.search([('order_id.state', 'in', ('draft', 'sent')),
                          ('display_type', '=', False),
                          ('product_id.default_code', '!=', False)])
still_coded = open_lines.filtered(
    lambda l: l.name and l.name.startswith("[%s] " % l.product_id.default_code))
check("open quotations cleaned by the migration", not still_coded,
      "%s of %s lines still start with a code" % (len(still_coded), len(open_lines)))
if product:
    partner = env['res.partner'].sudo().search([], limit=1)
    order = env['sale.order'].new({'partner_id': partner.id})
    line = Line.new({'order_id': order, 'product_id': product.id})
    check("new quotation line has no code", not line.name.startswith("[%s]" % product.default_code),
          repr(line.name.split("\n")[0]))
    check("form shows the name once", line.name.startswith(line.translated_product_name or ""),
          repr(line.translated_product_name))

# ---------------------------------------------------------------- round trip
print("\nBACK OFFICE ROUND TRIP")
from odoo.addons.pos_retail.controllers import back_office_pin
source = inspect.getsource(back_office_pin.PosRetailBackOfficePin)
check("Back to Till returns to the till's own login", "'till_uid'" in source and "marker.get('till_uid')" in source)
for cfg in env['pos.config'].sudo().search([('active', '=', True)]):
    kiosk = cfg.pos_retail_kiosk_user_id
    print("         %-26s employees login %-3s kiosk account %s" % (
        cfg.name[:26], 'on' if cfg.module_pos_hr else 'OFF', kiosk.login if kiosk else '-'))

# ---------------------------------------------------------------- summary
print("\n" + "=" * 78)
failed = [r for r in results if not r[1] and r[3] == 'FAIL']
warned = [r for r in results if not r[1] and r[3] == 'WARN']
print("%s checks, %s failed, %s warnings" % (len(results), len(failed), len(warned)))
if failed:
    print("\nFAILED:")
    for name, _ok, detail, _sev in failed:
        print("  - %s   %s" % (name.strip(), detail))
else:
    print("\nRelease verified. Now the browser checks: close every POS tab, then reopen.")
print("=" * 78)

env.cr.rollback()
