# Part of pos_retail.
#
# Run this script on the server using:
#   su -s /bin/bash odoo -c '/opt/odoo/venv/bin/python3 /opt/odoo/odoo/odoo-bin shell -c /etc/odoo/odoo.conf -d ostore_live --no-http < /opt/odoo/custom_addons/pos_retail/scripts/audit_pos_manager_and_roles.py'

print("\n" + "=" * 70)
print("       POS RETAIL: MANAGER & DISCOUNT ROLE CONFIGURATION AUDIT")
print("=" * 70)

# 1. Module pos_retail
mod = env['ir.module.module'].sudo().search([('name', '=', 'pos_retail')], limit=1)
mod_state = mod.state if mod else 'NOT FOUND'
print("\n[1] Module 'pos_retail' state: %s" % mod_state)

# 2. View in database
view = env['ir.ui.view'].sudo().search([('name', '=', 'hr.employee.form.inherit.pos_retail')], limit=1)
if view:
    print("[2] Form View 'hr.employee.form.inherit.pos_retail': INSTALLED (View ID %s)" % view.id)
    print("    -> 'POS Discount Role' field is available on Employee form.")
else:
    print("[2] Form View 'hr.employee.form.inherit.pos_retail': NOT INSTALLED IN DB")
    print("    -> You need to upgrade pos_retail (-u pos_retail) after git pull.")

# 3. Discount Roles
print("\n[3] POS Discount Roles (pos.retail.discount.role):")
roles = env['pos.retail.discount.role'].sudo().search([])
if not roles:
    print("    -> No discount roles found!")
for r in roles:
    print("    - ID: %-2d | Name: %-18s | Can Approve: %-5s | Unlimited: %s" % (
        r.id, r.name or '', str(bool(r.can_approve)), str(bool(r.is_unlimited))
    ))

# 4. Employees
print("\n[4] Employees (hr.employee):")
employees = env['hr.employee'].sudo().search([])
approvers_found = []
for emp in employees:
    has_pin = bool(emp.pin)
    pin_str = "PIN SET" if has_pin else "NO PIN"
    role_name = emp.pos_discount_role_id.name if emp.pos_discount_role_id else "(No Role)"
    can_approve = bool(emp.pos_discount_role_id and emp.pos_discount_role_id.can_approve)
    user_name = emp.user_id.name if emp.user_id else "No user"
    is_pos_admin = bool(emp.user_id and emp.user_id.has_group('point_of_sale.group_pos_manager'))
    
    status_flags = []
    if can_approve or is_pos_admin:
        if has_pin:
            status_flags.append("READY TO APPROVE")
            approvers_found.append(emp)
        else:
            status_flags.append("NEEDS PIN!")
    else:
        status_flags.append("Cashier only")
        
    print("    - ID: %-2d | Name: %-18s | %-8s | Role: %-14s | Approver: %-5s | %s" % (
        emp.id, emp.name or '', pin_str, role_name, str(can_approve or is_pos_admin), " | ".join(status_flags)
    ))

# 5. POS Registers
print("\n[5] POS Registers (pos.config):")
configs = env['pos.config'].sudo().search([])
for cfg in configs:
    emp_login = bool(cfg.module_pos_hr)
    allowed = (cfg.basic_employee_ids | cfg.advanced_employee_ids).mapped('name')
    allowed_str = ", ".join(allowed) if allowed else "ALL employees allowed"
    print("    - Register: %s (ID %s) | Employee Login: %s" % (cfg.name, cfg.id, emp_login))
    print("      Allowed Cashiers: %s" % allowed_str)

print("\n" + "=" * 70)

# 6. Auto-Fix Check
if not approvers_found:
    print("\n[ACTION REQUIRED] No active manager with a PIN was found!")
    print("Configuring Administrator as POS Manager with PIN 1234 now...")
    
    manager_role = env['pos.retail.discount.role'].sudo().search([('can_approve', '=', True)], limit=1)
    if not manager_role:
        manager_role = env['pos.retail.discount.role'].sudo().create({
            'name': 'Manager',
            'sequence': 30,
            'is_unlimited': True,
            'can_approve': True,
        })
        
    target_emp = env['hr.employee'].sudo().search([('user_id.login', 'in', ['admin', 'mitchell'])], limit=1) \
              or env['hr.employee'].sudo().search([('user_id', '!=', False)], limit=1) \
              or env['hr.employee'].sudo().search([], limit=1)
              
    if target_emp:
        target_emp.write({
            'pos_discount_role_id': manager_role.id,
            'pin': '1234',
        })
        print(" -> Assigned '%s' to employee '%s' with PIN '1234'." % (manager_role.name, target_emp.name))
        
        for cfg in configs:
            if cfg.module_pos_hr and target_emp not in (cfg.basic_employee_ids | cfg.advanced_employee_ids):
                cfg.write({'advanced_employee_ids': [(4, target_emp.id)]})
                print(" -> Added '%s' to POS register '%s'." % (target_emp.name, cfg.name))
                
        env.cr.commit()
        print(" -> SUCCESS: Saved to database! Employee '%s' can now approve with PIN 1234." % target_emp.name)
    else:
        print(" -> Could not find an employee record to configure.")
else:
    names = ", ".join(e.name for e in approvers_found)
    print("\n[STATUS: OK] Found ready manager(s): %s" % names)
    print("They can authenticate overrides using their configured PIN.")

print("=" * 70 + "\n")
