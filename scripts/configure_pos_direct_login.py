#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Configure POS Direct Login, Register Assignment, and Zero-Admin Morning Session
Opening for all POS Cashiers and Users.

Usage:
  # Via Odoo Shell:
  python3 odoo-bin shell -c /etc/odoo/odoo.conf -d <db_name> < configure_pos_direct_login.py

  # Or executed standalone:
  python3 configure_pos_direct_login.py -c /etc/odoo/odoo.conf -d <db_name>
"""

import sys
import logging

_logger = logging.getLogger(__name__)

def configure_pos_users(env):
    pos_user_group = env.ref('point_of_sale.group_pos_user', raise_if_not_found=False)
    admin_group = env.ref('base.group_system', raise_if_not_found=False)

    if not pos_user_group:
        print("[!] Error: point_of_sale.group_pos_user group not found.")
        return

    # Find all active POS configs
    configs = env['pos.config'].search([('active', '=', True)])
    if not configs:
        print("[!] Error: No active POS configs found.")
        return

    print("================================================================================")
    print(f"ACTIVE POS REGISTERS ({len(configs)} found):")
    for cfg in configs:
        print(f"  * Config #{cfg.id}: '{cfg.name}' | Company: '{cfg.company_id.name}' (ID {cfg.company_id.id}) | Employees: {len(cfg.basic_employee_ids)}")
    print("================================================================================")

    # Find all users with POS access (excluding OdooBot)
    users = env['res.users'].search([
        ('group_ids', 'in', [pos_user_group.id]),
        ('id', '!=', 1),
        ('share', '=', False),
    ])

    print(f"\nProcessing {len(users)} POS users...\n")
    configured_cashiers = []
    admins = []

    for user in users:
        is_admin = bool(admin_group and admin_group in user.group_ids)

        if is_admin:
            # Super Administrators: keep backend access safe, do NOT restrict backend!
            admins.append(user)
            user.sudo().write({
                'pos_restrict_backend': False,
            })
            print(f"[ADMIN SAFE] User #{user.id} '{user.login}' ({user.name}): Kept unrestricted backend access (/odoo).")
            continue

        # Cashier User: Find best-matching POS Config
        target_config = user.pos_config_id
        if not target_config or not target_config.active:
            # Match by user company first
            matching_configs = configs.filtered(lambda c: c.company_id.id == user.company_id.id)
            if matching_configs:
                target_config = matching_configs[0]
            else:
                target_config = configs[0]

        # Update user fields for POS Direct Login
        vals = {
            'pos_direct_login': True,
            'pos_config_id': target_config.id,
            'pos_auto_open_session': True,
            'pos_restrict_backend': True,
        }
        user.sudo().write(vals)

        # Ensure POS access, company alignment, and linked hr.employee without PIN
        user.sudo()._ensure_pos_access_and_company()

        # Find or verify linked employee
        emp = env['hr.employee'].sudo().search([('user_id', '=', user.id)], limit=1)
        if emp:
            # Clear PIN so cashier jumps straight into sales register without lock screen
            emp.sudo().write({'pin': False})
            # Ensure employee is enrolled in the POS register
            if emp not in target_config.basic_employee_ids and emp not in target_config.advanced_employee_ids:
                target_config.sudo().write({'basic_employee_ids': [(4, emp.id)]})

        configured_cashiers.append((user, target_config, emp))
        print(f"[CASHIER CONFIGURED] User #{user.id} '{user.login}' ({user.name}) -> Register: '{target_config.name}' (ID {target_config.id}) | Direct: Yes | AutoOpen: Yes | RestrictBackend: Yes | Employee: '{emp.name if emp else 'N/A'}' (PIN bypassed)")

    print("\n================================================================================")
    print(f"CONFIGURATION SUMMARY:")
    print(f"  * {len(configured_cashiers)} Cashier(s) configured for Direct POS Login:")
    for u, cfg, emp in configured_cashiers:
        print(f"    - {u.login} ({u.name}) -> {cfg.name} (Direct Login: YES, Backend Restricted: YES)")
    print(f"  * {len(admins)} Admin(s) protected (Backend Restricted: NO):")
    for a in admins:
        print(f"    - {a.login} ({a.name})")
    print("================================================================================")
    print("Success! All cashiers are now set to jump directly into the sales register upon login.")


# Check if running in odoo shell (where 'env' is already defined)
if 'env' in locals():
    configure_pos_users(env)
    env.cr.commit()
elif __name__ == '__main__':
    import os
    # Automatically add odoo and workspace path to sys.path if not present
    script_dir = os.path.dirname(os.path.abspath(__file__))
    candidates = [
        os.path.abspath(os.path.join(script_dir, '../../..')),
        os.path.abspath(os.path.join(script_dir, '../../../odoo')),
        '/opt/odoo',
        '/opt/odoo/odoo',
    ]
    for c in candidates:
        if os.path.isdir(c) and c not in sys.path:
            sys.path.insert(0, c)

    import odoo
    from odoo import api, SUPERUSER_ID
    from odoo.modules.registry import Registry

    # Parse command line args using Odoo's config parser
    odoo.tools.config.parse_config(sys.argv[1:])
    dbname = odoo.tools.config['db_name']
    if isinstance(dbname, (list, tuple)):
        dbname = dbname[0]
    elif dbname:
        dbname = str(dbname).split(',')[0].strip()

    if not dbname:
        print("[!] Error: No database specified. Use -d <database_name>")
        sys.exit(1)

    registry = Registry(dbname)
    with registry.cursor() as cr:
        env = api.Environment(cr, SUPERUSER_ID, {})
        configure_pos_users(env)
        cr.commit()
