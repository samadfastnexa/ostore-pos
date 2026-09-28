"""Remove the 15% and 17% taxes from every product, and from the defaults.

    venv/Scripts/python.exe odoo/odoo-bin shell -c odoo.conf -d <db> --no-http \
        < custom_addons/pos_retail/scripts/remove_product_taxes.py

On the server (dry run, then APPLY=1 to write):
    sudo -u odoo env APPLY=1 /opt/odoo/venv/bin/python3 /opt/odoo/odoo/odoo-bin shell \
        -c /etc/odoo/odoo.conf -d ostore_live --no-http \
        < /opt/odoo/custom_addons/pos_retail/scripts/remove_product_taxes.py

The owner charges no 15% or 17% tax: the sheet's price is the price. With
both on a product the till added 32% (Rs 3,500 rang up as Rs 4,620, above the
MRP). This takes every 15% and 17% percent tax off every product -- customer
and vendor side -- and off each company's "default taxes" so new products do
not pick them up again. The tax records themselves are kept (past invoices
refer to them); other rates, e.g. an 18% GST, are not touched.

DRY RUN unless APPLY=1.
"""

import os

APPLY = os.environ.get('APPLY', '').strip().lower() in ('1', 'true', 'yes')
RATES = [15.0, 17.0]

Tax = env['account.tax'].sudo().with_context(active_test=False)
Template = env['product.template'].sudo().with_context(active_test=False)
taxes = Tax.search([('amount_type', '=', 'percent'), ('amount', 'in', RATES)])

print()
print("=" * 78)
print("REMOVE 15% / 17% TAXES" + ("" if APPLY else "   (DRY RUN -- nothing written)"))
print("=" * 78)
for tax in taxes:
    on_sale = Template.search_count([('taxes_id', 'in', tax.id)])
    on_purchase = Template.search_count([('supplier_taxes_id', 'in', tax.id)])
    print(f"  {tax.name:24s} {tax.type_tax_use:9s} {tax.company_id.name:24s} "
          f"customer tax on {on_sale} products, vendor tax on {on_purchase}")
defaults = [(company, field) for company in env['res.company'].sudo().search([])
            for field in ('account_sale_tax_id', 'account_purchase_tax_id') if company[field] in taxes]
for company, field in defaults:
    print(f"  default {'sales' if 'sale' in field else 'purchase'} tax of {company.name}: "
          f"{company[field].name} -> none")
other = Tax.search([('id', 'not in', taxes.ids), ('amount', '!=', 0)])
if other:
    print(f"  left as they are (other rates): {', '.join(other.mapped('name'))}")

if APPLY:
    for tax in taxes:
        Template.search([('taxes_id', 'in', tax.id)]).write({'taxes_id': [(3, tax.id)]})
        Template.search([('supplier_taxes_id', 'in', tax.id)]).write({'supplier_taxes_id': [(3, tax.id)]})
    for company, field in defaults:
        company.write({field: False})
    env.cr.commit()
    still = Template.search_count(['|', ('taxes_id', 'in', taxes.ids), ('supplier_taxes_id', 'in', taxes.ids)])
    print(f"\nDone. Products still carrying a 15%/17% tax: {still}. Reload the till pages.")
else:
    print("\nNothing was written; run with APPLY=1.")
print("=" * 78)
