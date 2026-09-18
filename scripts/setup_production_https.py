# Enforce HTTPS Base URL in Database & Freeze Parameters
#
# Usage:
#   sudo -u odoo /opt/odoo/venv/bin/python3 /opt/odoo/odoo/odoo-bin shell \
#       -c /etc/odoo/odoo.conf -d ostore_live --no-http \
#       < /opt/odoo/custom_addons/pos_retail/scripts/setup_production_https.py

print('===========================================================')
print('CONFIGURING HTTPS SECURE BASE URL & SYSTEM PARAMETERS')
print('===========================================================')

ICP = env['ir.config_parameter'].sudo()

# 1. Set web.base.url to genuine HTTPS domain
target_url = 'https://169-58-143-45.sslip.io'
ICP.set_param('web.base.url', target_url)
print(f'[OK] web.base.url set to: {target_url}')

# 2. Freeze web.base.url so incoming HTTP requests or workers do not rewrite it
ICP.set_param('web.base.url.freeze', 'True')
print('[OK] web.base.url.freeze set to: True')

# 3. Verify
current_url = ICP.get_param('web.base.url')
is_frozen = ICP.get_param('web.base.url.freeze')
print(f'[VERIFIED] web.base.url: {current_url}')
print(f'[VERIFIED] web.base.url.freeze: {is_frozen}')

env.cr.commit()
print('===========================================================')
print('DATABASE HTTPS CONFIGURATION COMMITTED SUCCESSFULLY!')
print('===========================================================')
