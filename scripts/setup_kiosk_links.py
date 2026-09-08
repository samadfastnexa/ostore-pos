"""Set the Kiosk Sign-in Account on every register that has a matching till
user, so each till's "Kiosk Link" tab gets a working link. Idempotent: running
it again just confirms nothing needs to change.

Matches by NAME, not by hardcoded id, so the same script runs unmodified on
the laptop and on the server even though ids differ between the two:

    laptop:  Branch 2 -> till login "cash"          branch 1 -> "till.branch1"
    server:  match your own registers/logins in TILL_LOGIN_BY_COMPANY below

    venv/Scripts/python.exe odoo/odoo-bin shell -c odoo.conf -d <db> --no-http \
        < custom_addons/pos_retail/scripts/setup_kiosk_links.py

On the server:
    sudo -u odoo /opt/odoo/venv/bin/python3 /opt/odoo/odoo/odoo-bin shell \
        -c /etc/odoo/odoo.conf -d ostore_live --no-http \
        < /opt/odoo/custom_addons/pos_retail/scripts/setup_kiosk_links.py

Safe to run more than once: a register that already has the right kiosk user
set is left untouched (and keeps its existing link -- this never regenerates
a token on its own). A register whose kiosk user is wrong is corrected and
gets a fresh token, since a token issued for the OLD account would sign
anyone using it into the wrong login.
"""

# Company name -> which existing user's login becomes that branch's kiosk
# account. Edit this before running somewhere the branch/login names differ.
TILL_LOGIN_BY_COMPANY = {
    'Branch 2': 'cash',
    'branch 1': 'till.branch1',
}

Config = env['pos.config'].sudo()
Users = env['res.users'].sudo()

for company_name, login in TILL_LOGIN_BY_COMPANY.items():
    user = Users.search([('login', '=', login)], limit=1)
    if not user:
        print("  [SKIP] %-10s -> no user with login %r exists here" % (company_name, login))
        continue

    configs = Config.search([('company_id.name', '=', company_name)])
    if not configs:
        print("  [SKIP] %-10s -> no register found for this company" % company_name)
        continue

    for config in configs:
        if config.pos_retail_kiosk_user_id == user and config.pos_retail_kiosk_token:
            print("  [OK]   %-24s already set to %s" % (config.name, login))
            continue
        config.pos_retail_kiosk_user_id = user.id
        env.cr.commit()
        config.invalidate_recordset()
        print("  [SET]  %-24s -> %s" % (config.name, login))

env.cr.commit()

print()
print("=" * 78)
print("KIOSK LINKS")
print("=" * 78)
for config in Config.search([('pos_retail_kiosk_user_id', '!=', False)]):
    print("  %-24s (%s)" % (config.name, config.company_id.name))
    print("      signs in as : %s" % config.pos_retail_kiosk_user_id.login)
    print("      link        : %s" % config.pos_retail_kiosk_url)
    print()

without = Config.search([('pos_retail_kiosk_user_id', '=', False)])
if without:
    print("Still off (no kiosk account set): %s" % without.mapped('name'))
