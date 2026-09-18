# Make all products and the discount product global across all branches.
#
# Usage:
#   sudo -u odoo /opt/odoo/venv/bin/python3 /opt/odoo/odoo/odoo-bin shell \
#       -c /etc/odoo/odoo.conf -d ostore_live --no-http \
#       < /opt/odoo/custom_addons/pos_retail/scripts/make_catalogue_global.py

print('===========================================================')
print('MAKING CATALOGUE & DISCOUNT PRODUCT GLOBAL EVERYWHERE')
print('===========================================================')

# 1. Fix discount product
prod = env.ref('pos_discount.product_product_consumable', raise_if_not_found=False)
if not prod:
    prod = env['product.product'].sudo().search([('name', 'ilike', 'Discount')], limit=1)

if prod:
    prod.sudo().write({
        'company_id': False,
        'active': True,
        'sale_ok': True,
    })
    if prod.product_tmpl_id:
        prod.product_tmpl_id.sudo().write({
            'company_id': False,
            'active': True,
            'sale_ok': True,
        })
    print(f'[OK] Discount Product set to GLOBAL: ID {prod.id} ({prod.display_name})')
else:
    print('[WARN] No discount product found!')

# 2. Assign to all POS configs
configs = env['pos.config'].sudo().search([])
for cfg in configs:
    if prod:
        cfg.discount_product_id = prod.id
    print(f'[OK] POS Register: {cfg.name} (ID: {cfg.id}) -> Discount Product: {cfg.discount_product_id.name}')

# 3. Make all product templates and variants global
tmpl_updated = env['product.template'].sudo().search([('company_id', '!=', False)]).write({'company_id': False})
prod_updated = env['product.product'].sudo().search([('company_id', '!=', False)]).write({'company_id': False})
print(f'[OK] Cleared company_id on all products so they are globally available across every branch.')

env.cr.commit()
print('===========================================================')
print('DONE! Everything is now GLOBAL everywhere across all branches.')
print('===========================================================')
