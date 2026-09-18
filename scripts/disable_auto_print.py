# -*- coding: utf-8 -*-
# Disable Automatic Receipt Printing and Skip Preview Screen in POS Config
#
# Run with:
# sudo -u odoo /opt/odoo/venv/bin/python3 /opt/odoo/odoo/odoo-bin shell -c /etc/odoo/odoo.conf -d ostore_live --no-http < /opt/odoo/custom_addons/pos_retail/scripts/disable_auto_print.py

configs = env['pos.config'].search([])
count = 0
for cfg in configs:
    cfg.write({
        'iface_print_auto': False,
        'iface_print_skip_screen': False,
    })
    count += 1

env.cr.commit()
print(f"[OK] Successfully disabled iface_print_auto and iface_print_skip_screen on {count} POS configs.")
