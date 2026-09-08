"""Give every employee at a trading branch a till PIN, and print the new ones
once so they can be handed out.

    venv/Scripts/python.exe odoo/odoo-bin shell -c odoo.conf -d <db> --no-http \
        < custom_addons/pos_retail/scripts/set_employee_pins.py

On the server:
    sudo -u odoo /opt/odoo/venv/bin/python3 /opt/odoo/odoo/odoo-bin shell \
        -c /etc/odoo/odoo.conf -d ostore_live --no-http \
        < /opt/odoo/custom_addons/pos_retail/scripts/set_employee_pins.py

The kiosk link gets someone as far as the PIN pad and stops there. This is
the other half: without a PIN an employee cannot open a till at all.

Idempotent, and deliberately careful about which way it errs: an employee who
already has a PIN is LEFT ALONE and their PIN is not printed. Changing a PIN
that people have already memorised, or reprinting one into a terminal log
every time this runs, are both worse than doing nothing. To deliberately
change one, name it in PINS_BY_EMPLOYEE below.

PINs are chosen at random rather than 1111, 1234 and so on, and are unique
within a branch. They are digits only because hr.employee._verify_pin rejects
anything else.
"""

import random

# Optional: fix specific people's PINs instead of letting them be random.
# Names are matched exactly. Anyone here is set even if they already have one,
# which is how you change a PIN somebody has forgotten.
PINS_BY_EMPLOYEE = {
    # 'RASHID': '4821',
}

PIN_LENGTH = 4

# Not secrets so much as habits: these are the first things anyone tries.
WEAK = {'0000', '1111', '2222', '3333', '4444', '5555', '6666', '7777',
        '8888', '9999', '1234', '4321', '1122', '0123', '9876'}

Employee = env['hr.employee'].sudo()
Company = env['res.company'].sudo()

trading = Company.search([('child_ids', '=', False)])
assigned, kept, forced, skipped = [], [], [], []


def pin_in_use(company, pin):
    return bool(Employee.search_count([
        ('company_id', '=', company.id), ('pin', '=', pin)]))


def fresh_pin(company):
    for _ in range(500):
        pin = ''.join(str(random.randint(0, 9)) for _ in range(PIN_LENGTH))
        if pin not in WEAK and not pin_in_use(company, pin):
            return pin
    return None


for company in trading:
    for employee in Employee.search([('company_id', '=', company.id)]):
        chosen = PINS_BY_EMPLOYEE.get(employee.name)

        if chosen:
            if not chosen.isdigit():
                skipped.append((employee.name, company.name,
                                "the PIN given in PINS_BY_EMPLOYEE is not digits only"))
                continue
            employee.pin = chosen
            forced.append((company.name, employee.name, chosen))
            continue

        if employee.pin:
            kept.append((company.name, employee.name))
            continue

        pin = fresh_pin(company)
        if not pin:
            skipped.append((employee.name, company.name,
                            "could not find an unused PIN -- widen PIN_LENGTH"))
            continue
        employee.pin = pin
        assigned.append((company.name, employee.name, pin))

env.cr.commit()

print()
print("=" * 78)
print("NEW PINS -- write these down now, they are not printed again")
print("=" * 78)
if not assigned and not forced:
    print("  (nothing to set -- everyone at a trading branch already has one)")
for company_name, name, pin in assigned:
    print("  %-22s %-28s %s" % (company_name, name, pin))
for company_name, name, pin in forced:
    print("  %-22s %-28s %s   (changed on purpose)" % (company_name, name, pin))

if kept:
    print()
    print("Left alone, already had a PIN (not shown -- look on the employee form")
    print("under HR Settings if one needs recovering):")
    for company_name, name in kept:
        print("  %-22s %s" % (company_name, name))

if skipped:
    print()
    print("Skipped:")
    for name, company_name, why in skipped:
        print("  %-28s (%s) %s" % (name, company_name, why))

print()
print("A PIN only lets someone open a till. What they may then discount, and")
print("what needs a manager's approval on top, is the discount role on the")
print("employee, not this.")
