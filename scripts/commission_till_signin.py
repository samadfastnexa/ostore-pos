"""Give every trading branch a till account and a Kiosk Link, so the only
thing anyone at a counter types is their own PIN.

    venv/Scripts/python.exe odoo/odoo-bin shell -c odoo.conf -d <db> --no-http \
        < custom_addons/pos_retail/scripts/commission_till_signin.py

On the server:
    sudo -u odoo /opt/odoo/venv/bin/python3 /opt/odoo/odoo/odoo-bin shell \
        -c /etc/odoo/odoo.conf -d ostore_live --no-http \
        < /opt/odoo/custom_addons/pos_retail/scripts/commission_till_signin.py

Unlike setup_kiosk_links.py this needs no names filled in by hand: it works
from the branch structure itself. For each register belonging to a TRADING
branch (a company with no children of its own):

  * already has a kiosk account   -> left alone, link reprinted
  * exactly one plain till account exists in that company -> reuse it
  * none exists                   -> create one
  * several exist                 -> lists them and changes nothing, because
                                     which account a kiosk link signs in as is
                                     the shop's decision, not a guess

"Plain" deliberately excludes anyone who can reach Settings or approve
discounts as a POS manager. A kiosk link hands whoever holds it that account,
so it must be the most boring login in the building: one company, Point of
Sale only, nothing else.

Accounts are created WITHOUT a password. That is not an oversight -- the
kiosk link is how the till signs in, and an account with no password cannot
be signed into any other way, which is one less credential on a counter.
Set one from Settings later if a fallback is ever wanted.

Registers on a PARENT company are skipped: a parent holds the legal identity
only, and a till there would be selling from a company with no catalogue.
Fix that with scripts/check_branch_setup.py and commission_branch.py rather
than by giving it a sign-in.
"""

Config = env['pos.config'].sudo()
Users = env['res.users'].sudo()
Employee = env['hr.employee'].sudo()

group_user = env.ref('base.group_user')
group_pos_user = env.ref('point_of_sale.group_pos_user')

created, reused, kept, skipped = [], [], [], []


def plain_till_candidates(company):
    """Internal POS users in this company who are neither administrators nor
    POS managers -- the only kind of account safe to put behind a kiosk link."""
    users = Users.search([
        ('company_ids', 'in', company.id),
        ('share', '=', False),
        ('active', '=', True),
    ])
    return users.filtered(
        lambda u: u.has_group('point_of_sale.group_pos_user')
        and not u.has_group('base.group_system')
        and not u.has_group('point_of_sale.group_pos_manager')
    )


def make_till_account(company):
    slug = ''.join(
        ch if ch.isalnum() else '.' for ch in (company.name or 'branch').lower()
    ).strip('.')
    while '..' in slug:
        slug = slug.replace('..', '.')
    login = 'till.%s' % slug
    suffix = 1
    while Users.with_context(active_test=False).search_count([('login', '=', login)]):
        suffix += 1
        login = 'till.%s.%s' % (slug, suffix)
    return Users.create({
        'name': '%s Till' % company.name,
        'login': login,
        'company_id': company.id,
        'company_ids': [(6, 0, [company.id])],
        'group_ids': [(6, 0, [group_user.id, group_pos_user.id])],
    })


for config in Config.search([]):
    company = config.company_id
    if company.child_ids:
        skipped.append((config.name, company.name,
                        "parent company -- holds the legal identity, should not trade"))
        continue

    if config.pos_retail_kiosk_user_id:
        kept.append(config)
        continue

    candidates = plain_till_candidates(company)
    if len(candidates) > 1:
        skipped.append((config.name, company.name,
                        "several possible accounts: %s -- set one by hand"
                        % ', '.join(candidates.mapped('login'))))
        continue

    if candidates:
        user = candidates[0]
        reused.append((config.name, user.login))
    else:
        user = make_till_account(company)
        created.append((config.name, user.login))

    config.pos_retail_kiosk_user_id = user.id
    env.cr.commit()
    config.invalidate_recordset()

env.cr.commit()

print()
print("=" * 78)
print("TILL SIGN-IN")
print("=" * 78)
for name, login in created:
    print("  [NEW]   %-28s created and wired to %r (no password, kiosk only)" % (name, login))
for name, login in reused:
    print("  [REUSE] %-28s wired to the account already there: %r" % (name, login))
for config in kept:
    print("  [KEPT]  %-28s already had %r" % (config.name, config.pos_retail_kiosk_user_id.login))
for name, company_name, why in skipped:
    print("  [SKIP]  %-28s (%s) %s" % (name, company_name, why))

print()
print("=" * 78)
print("LINKS TO BOOKMARK, ONE PER TILL DEVICE")
print("=" * 78)
for config in Config.search([('pos_retail_kiosk_user_id', '!=', False)]):
    print("  %s  (%s)" % (config.name, config.company_id.name))
    print("      %s" % config.pos_retail_kiosk_url)
    print()

# The link only gets someone as far as the PIN pad. Without a PIN on the
# employee, the second half of the flow has nothing to check.
print("=" * 78)
print("PINS -- the other half of the flow")
print("=" * 78)
for company in Config.search([]).mapped('company_id').filtered(lambda c: not c.child_ids):
    staff = Employee.search([('company_id', '=', company.id)])
    without_pin = staff.filtered(lambda e: not e.pin)
    print("  %s: %s employee(s), %s without a PIN" % (
        company.name, len(staff), len(without_pin)))
    for employee in without_pin:
        print("      no PIN yet: %s" % employee.name)
if not Employee.search([]):
    print("  no employees exist yet -- nobody can pass the PIN screen until they do")
