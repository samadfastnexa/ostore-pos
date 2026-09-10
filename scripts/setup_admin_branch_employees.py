"""Let the owner sign in at every branch till, not just the parent's.

    venv/Scripts/python.exe odoo/odoo-bin shell -c odoo.conf -d <db> --no-http \
        < custom_addons/pos_retail/scripts/setup_admin_branch_employees.py

On the server:
    sudo -u odoo /opt/odoo/venv/bin/python3 /opt/odoo/odoo/odoo-bin shell \
        -c /etc/odoo/odoo.conf -d ostore_live --no-http \
        < /opt/odoo/custom_addons/pos_retail/scripts/setup_admin_branch_employees.py

THE FAULT. Adding every branch to the user's Companies list looked like it
should be enough, and it is not. The till does not ask "which companies may
this user enter". It asks "which employees belong to THIS register's
company", and it asks it with the plain company check, not the parent-aware
one -- see pos_hr/models/pos_config.py _employee_domain, which builds on
_check_company_domain(self.company_id), and note that hr.employee never
overrides that method. So the domain is company_id in [branch, False].

An employee sitting on the parent company therefore cannot appear at a
branch counter. Not a permission problem, and no amount of ticking boxes on
the user fixes it.

WHY A SECOND RECORD RATHER THAN MOVING THE FIRST. A user is allowed many
employee records -- employee_ids is a one2many on res.users, and employee_id
resolves to whichever one sits in the company you are currently in. That is
Odoo's intended shape for a person who works across companies. Moving the
parent record to a branch would fix the branch and break the parent.

THE PIN IS COPIED, NOT INVENTED. One person should have one PIN to remember,
whichever counter they are standing at. The existing parent record's PIN is
reused, so nothing new has to be memorised or written down. If the parent
record has no PIN, set PIN_FALLBACK below rather than letting this create a
PIN-less record: a PIN-less employee can be selected at the till by anyone.

RESTRICTED REGISTERS ARE HANDLED. If a register names its allowed employees
explicitly, _employee_domain adds a second condition, and a new employee not
on any of those lists still would not show. Where that applies the new
record is added to the register's manager-access list, which matches what
the owner is.

READ ONLY until APPLY is set to True.
"""

APPLY = False

# Used only if the parent employee record carries no PIN of its own. Left
# deliberately as None so the script stops and says so, rather than quietly
# creating an employee anyone can select without typing anything.
PIN_FALLBACK = None

Company = env['res.company'].sudo()
Employee = env['hr.employee'].sudo()
Users = env['res.users'].sudo()
PosConfig = env['pos.config'].sudo()

admin = env.ref('base.user_admin', raise_if_not_found=False) or Users.search(
    [('login', '=', 'admin@gmail.com')], limit=1)

print()
print("=" * 78)
print("OWNER AT EVERY TILL" + ("" if APPLY else "   (DRY RUN -- nothing written)"))
print("=" * 78)

if not admin:
    print("  Could not find the administrator user. Nothing done.")
else:
    print("  User: %r  (login %r)" % (admin.name, admin.login))
    print("  Allowed companies: %s" % ", ".join(admin.company_ids.mapped('name')))
    print()

    existing = Employee.search([('user_id', '=', admin.id)])
    by_company = {e.company_id.id: e for e in existing}

    print("  Employee records this user already has:")
    for employee in existing:
        print("      %-26r company=%-24r pin=%s" % (
            employee.name[:24], employee.company_id.name[:22],
            "set" if employee.pin else "MISSING"))
    if not existing:
        print("      (none)")

    # The PIN to carry across. Prefer whichever existing record has one, so
    # this stays correct even if the parent record is not the first one.
    source_pin = next((e.pin for e in existing if e.pin), None) or PIN_FALLBACK

    # Only companies that actually run a till need a record. Creating one on
    # a company with no register would be clutter nobody asked for.
    till_companies = PosConfig.search([('active', '=', True)]).mapped('company_id')
    wanted = admin.company_ids & till_companies
    missing = wanted.filtered(lambda c: c.id not in by_company)

    print()
    print("  Companies running a till: %s" % (", ".join(till_companies.mapped('name')) or "none"))

    if not missing:
        print()
        print("  Every till company already has a record for this user. Nothing to add.")
        print("  If sign-in still fails, the cause is elsewhere: check that the")
        print("  register has employee login switched on, and that the record for")
        print("  that branch carries a PIN.")
    elif not source_pin:
        print()
        print("  STOPPING. No existing record carries a PIN, so there is nothing to")
        print("  copy, and creating a PIN-less employee would let anyone select the")
        print("  owner at the till without typing anything. Set a PIN on the parent")
        print("  record first, or set PIN_FALLBACK at the top of this file.")
    else:
        print()
        print("  Would create (PIN copied from the existing record):" if not APPLY
              else "  Creating (PIN copied from the existing record):")
        for company in missing:
            print("      %-26r on %r" % (admin.name, company.name))

        if APPLY:
            for company in missing:
                # with_company so the branch supplies the defaults it should:
                # working schedule, address, and the company stamp itself.
                employee = Employee.with_company(company).create({
                    'name': admin.name,
                    'user_id': admin.id,
                    'company_id': company.id,
                    'pin': source_pin,
                })
                by_company[company.id] = employee

                # A register that names its employees explicitly would still
                # not show this one. Manager access, because that is what the
                # owner is, and because the Admin Panel entry in the till is
                # gated on the manager role.
                for config in PosConfig.search([('company_id', '=', company.id)]):
                    if (config.basic_employee_ids or config.advanced_employee_ids
                            or config.minimal_employee_ids):
                        config.advanced_employee_ids = [(4, employee.id)]
                        print("      added to the allowed list on register %r" % config.name)

            env.cr.commit()

    print()
    print("  Where the owner can now sign in:")
    for config in PosConfig.search([('active', '=', True)]):
        employee = by_company.get(config.company_id.id)
        if not employee:
            state = "NO -- no employee record on %r" % config.company_id.name
        elif not employee.pin:
            state = "record exists but has NO PIN"
        elif not config.module_pos_hr:
            state = "record ready, but employee login is OFF on this register"
        else:
            state = "yes, PIN %s" % employee.pin
        print("      %-26r %s" % (config.name[:24], state))

    if not APPLY and missing and source_pin:
        print()
        print("=" * 78)
        print("Nothing was written. Set APPLY = True, or pipe it:")
        print("  sed 's/^APPLY = False/APPLY = True/' <this file> | odoo-bin shell ...")
        print("=" * 78)
