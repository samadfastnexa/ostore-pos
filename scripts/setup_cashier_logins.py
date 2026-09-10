"""Give cashiers a login, so permissions have somewhere to attach.

    sudo -u odoo /opt/odoo/venv/bin/python3 /opt/odoo/odoo/odoo-bin shell \
        -c /etc/odoo/odoo.conf -d ostore_live --no-http \
        < /opt/odoo/custom_addons/pos_retail/scripts/setup_cashier_logins.py

WHY THIS IS NEEDED. Permissions in the Roles & Permissions catalogue attach
to a LOGIN, not to an employee record. A cashier who exists only as an
employee with a PIN has no login, so there is nothing to grant anything to,
and every permission ticked for them silently does nothing. The Khata
Payment button not appearing at the till is that, seen from the counter.

A PIN and a login are not the same thing and are not interchangeable:

    PIN    says WHO is serving. Typed at the till, every shift. Identifies
           the person on the sale. Protects nothing else.
    LOGIN  says what that person is ALLOWED to do. Carries the permissions,
           in the back office and, through them, in the till.

WHAT THIS DOES. For every employee with a PIN but no login it creates one,
in that employee's own company, adds it to the role named below, links it
back to the employee, and prints a password ONCE. It does not touch an
employee who already has a login.

THE ROLE IS NOT CREATED HERE, on purpose. Which permissions a cashier gets
is the shop's decision and it differs per shop; inventing one in a script
would be guessing at it. Build the role on the Roles & Permissions screen
first, then name it below.

READ ONLY until APPLY is set to True.
"""

APPLY = False

# The role every new login joins. Must already exist under
# Point of Sale > Configuration > Roles & Permissions.
ROLE_NAME = 'Cashier'

# Login is built from the employee's name, plus this, so the shop's logins
# are recognisable at a glance and cannot collide with a real email address.
LOGIN_SUFFIX = '@till.local'

import re
import secrets
import string

Employee = env['hr.employee'].sudo()
Users = env['res.users'].sudo()
Role = env['pos.retail.access.role'].sudo()

role = Role.search([('name', '=', ROLE_NAME)], limit=1)
employees = Employee.search([('user_id', '=', False)])

line_break = "=" * 78
print()
print(line_break)
print("CASHIER LOGINS" + ("" if APPLY else "   (DRY RUN -- nothing written)"))
print(line_break)

if not role:
    print()
    print("  No role named %r exists." % ROLE_NAME)
    print("  Build it first: Point of Sale > Configuration > Roles & Permissions,")
    print("  tick the permissions it should carry, then set ROLE_NAME above to")
    print("  match. Nothing is created without one, because a login with no role")
    print("  can sign in and see nothing, which looks broken rather than restricted.")
else:
    print()
    print("  Role: %r" % role.name)
    print("  Grants: %s" % (", ".join(role.permission_ids.mapped('name')) or "nothing yet"))

    print()
    print("  Employees with a PIN but no login:")
    if not employees:
        print("      none -- every employee already has one")
    for employee in employees:
        print("      %-20s %-24s pin=%s" % (
            employee.name[:18], employee.company_id.name[:22],
            "set" if employee.pin else "MISSING"))

    def make_login(employee):
        """A login built from the name: readable, and obviously not an email
        anyone will try to send mail to."""
        base = re.sub(r'[^a-z0-9]+', '.', (employee.name or 'cashier').lower()).strip('.')
        candidate = base + LOGIN_SUFFIX
        suffix = 1
        while Users.with_context(active_test=False).search_count([('login', '=', candidate)]):
            suffix += 1
            candidate = "%s%s%s" % (base, suffix, LOGIN_SUFFIX)
        return candidate

    if not APPLY:
        print()
        print("  Would create:")
        for employee in employees:
            print("      %-20s login %s" % (employee.name[:18], make_login(employee)))
        print()
        print(line_break)
        print("Nothing was written. Set APPLY = True, or pipe it:")
        print("  sed 's/^APPLY = False/APPLY = True/' <this file> | odoo-bin shell ...")
        print(line_break)
    elif employees:
        alphabet = string.ascii_letters + string.digits
        created = []
        for employee in employees:
            company = employee.company_id
            # Passwords are generated rather than set to something memorable.
            # A shared or guessable password on an account that carries real
            # permissions undoes the permissions.
            password = ''.join(secrets.choice(alphabet) for _ in range(10))
            login = make_login(employee)
            user = Users.create({
                'name': employee.name,
                'login': login,
                'password': password,
                # The employee's OWN company, and only that one. A cashier
                # allowed into several companies can switch into a branch that
                # is not theirs and see its customers and its takings.
                'company_id': company.id,
                'company_ids': [(6, 0, [company.id])],
                'group_ids': [(4, env.ref('base.group_user').id), (4, role.group_id.id)],
            })
            employee.user_id = user.id
            created.append((employee, login, password))
        env.cr.commit()

        print()
        print("  Created. WRITE THESE DOWN -- the passwords are not shown again:")
        print()
        print("      %-20s %-30s %s" % ("CASHIER", "LOGIN", "PASSWORD"))
        for employee, login, password in created:
            print("      %-20s %-30s %s" % (employee.name[:18], login, password))
        print()
        print("  Their PIN is unchanged: that is still what they type at the till.")
        print("  The login is only for the back office, and for the permissions")
        print("  that reach into the till from it.")
