"""Put back the cashiers that Direct Login hid from the till.

    venv/Scripts/python.exe odoo/odoo-bin shell -c odoo.conf -d <db> --no-http \
        < custom_addons/pos_retail/scripts/restore_register_cashiers.py

On the server (dry run, then APPLY=1 to write):
    sudo -u odoo env APPLY=1 /opt/odoo/venv/bin/python3 /opt/odoo/odoo/odoo-bin shell \
        -c /etc/odoo/odoo.conf -d ostore_live --no-http \
        < /opt/odoo/custom_addons/pos_retail/scripts/restore_register_cashiers.py

THE FAULT. In pos_hr, a register whose cashier list (basic_employee_ids) is
empty lets every employee of its branch sign in; the moment the list holds
anyone, ONLY the listed employees can (pos_hr pos_config._employee_domain).
Direct Login added each direct-login cashier to that list, which silently
removed everybody else from the till.

WHAT THIS DOES. For each register whose list holds nothing but direct-login
cashiers -- i.e. the list only exists because of that mechanism -- the list
is cleared, so every branch employee can sign in again. Manager-access
employees keep their role. A register whose list names other people was set
up deliberately: it is reported with who is hidden, and left alone.

DRY RUN unless APPLY=1.
"""

import os

APPLY = os.environ.get('APPLY', '').strip().lower() in ('1', 'true', 'yes')

Config = env['pos.config'].sudo()
Employee = env['hr.employee'].sudo()
direct_users = env['res.users'].sudo().search([('pos_direct_login', '=', True)])
direct_emps = Employee.search([('user_id', 'in', direct_users.ids)])

print()
print("=" * 78)
print("RESTORE REGISTER CASHIERS" + ("" if APPLY else "   (DRY RUN -- nothing written)"))
print("=" * 78)
cleared = []
for cfg in Config.search([('module_pos_hr', '=', True)]):
    listed = cfg.basic_employee_ids
    company_emps = Employee.search([('company_id', 'in', [cfg.company_id.id, False])])
    print(f"\n{cfg.name}  ({cfg.company_id.name})")
    if not listed:
        print(f"  open to all {len(company_emps)} branch employees: {', '.join(company_emps.mapped('name')) or '-'}")
        continue
    allowed = listed | cfg.advanced_employee_ids | cfg.minimal_employee_ids
    hidden = company_emps - allowed
    print(f"  cashier list: {', '.join(listed.mapped('name'))}")
    print(f"  hidden from this till: {', '.join(hidden.mapped('name')) or '-'}")
    if listed <= direct_emps:
        print(f"  -> list holds only Direct Login cashiers: will clear it, "
              f"so all {len(company_emps)} branch employees can sign in")
        cleared.append(cfg)
    else:
        print("  -> list names other people too (set up deliberately): left alone. Add the hidden "
              "cashiers in Point of Sale > Configuration > Settings > Employees if they belong here.")

if APPLY and cleared:
    for cfg in cleared:
        cfg.write({'basic_employee_ids': [(5, 0, 0)]})
    env.cr.commit()
    print(f"\nCleared the cashier list on {len(cleared)} register(s). Reload the till pages.")
elif not APPLY:
    print(f"\nWould clear {len(cleared)} register(s). Nothing was written; run with APPLY=1.")
print("=" * 78)
