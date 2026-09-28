"""Replace the till's Card / JazzCash / EasyPaisa buttons with one "Online Payment".

DRY RUN unless APPLY=1: the first run only prints what it would change.

    venv/Scripts/python.exe odoo/odoo-bin shell -c odoo.conf -d OStore --no-http \
        < custom_addons/pos_retail/scripts/setup_online_payment.py
    (then again with APPLY=1 set in the environment)

On the server:
    sudo -u odoo env APPLY=0 /opt/odoo/venv/bin/python3 /opt/odoo/odoo/odoo-bin shell \
        -c /etc/odoo/odoo.conf -d ostore_live --no-http \
        < /opt/odoo/custom_addons/pos_retail/scripts/setup_online_payment.py
    (APPLY=1 to write)

For every register:
  * adds its company's "Online Payment" method, creating it with its own bank
    journal (code ONLN) the first time -- never without a journal, which Odoo
    would treat as Customer Account (the sale booked as the customer's debt);
  * removes every other bank-type method from the register (Card, JazzCash,
    EasyPaisa...). Cash and Customer Account (khata) stay as they are;
  * archives a removed method once no register uses it. Nothing is deleted:
    past sales keep showing the method they were paid with.

A register with an OPEN SESSION is left alone and listed: Odoo refuses
payment-method changes mid-session. Close that session, then run this again
before the till is reopened (a direct-login till opens a new session as soon
as it is loaded). Safe to run any number of times.
"""
import os

from odoo.addons.pos_retail import ONLINE_PAYMENT_NAME, _pos_retail_online_payment_method

APPLY = os.environ.get('APPLY') == '1'
Config = env['pos.config'].sudo()
removed = env['pos.payment.method'].sudo()
waiting = []

print("=" * 76)
print("ONLINE PAYMENT SETUP   db=%s   %s" % (env.cr.dbname, "(WRITING)" if APPLY else "(DRY RUN)"))
print("=" * 76)

for config in Config.search([], order='company_id, name'):
    methods = config.payment_method_ids
    online = methods.filtered(lambda m: m.name == ONLINE_PAYMENT_NAME)
    others = methods.filtered(lambda m: m.type == 'bank' and m.name != ONLINE_PAYMENT_NAME)
    print("\n%s   [%s]" % (config.name, config.company_id.name))
    print("  now:   %s" % ", ".join(methods.mapped('name')))

    if online and not others:
        print("  OK     already only Online Payment")
        continue
    if not online:
        print("  add    Online Payment")
    if others:
        print("  remove %s" % ", ".join(others.mapped('name')))

    if config.has_active_session:
        session = config.current_session_id
        state = dict(session._fields['state']._description_selection(env)).get(session.state, 'open')
        print("  WAIT   a session is open (%s, %s) -- close it, then run this again"
              % (session.name if session.name not in (False, '/') else 'new', state))
        waiting.append(config.name)
        continue
    if not APPLY:
        continue

    method = _pos_retail_online_payment_method(env, config.company_id)
    if not method:
        print("  SKIP   %s has no chart of accounts, so no bank journal can be made"
              % config.company_id.name)
        continue
    config.write({'payment_method_ids': [(4, method.id)] + [(3, m.id) for m in others]})
    # One commit per register: a later failure must not undo the ones done.
    env.cr.commit()
    removed |= others
    print("  DONE   now: %s" % ", ".join(config.payment_method_ids.mapped('name')))

if APPLY:
    for method in removed:
        if method.active and not method.config_ids:
            method.active = False
            print("\narchived %s [%s] (no register uses it; past sales keep it)"
                  % (method.name, method.company_id.name))
    env.cr.commit()

print("\n" + "=" * 76)
if waiting:
    print("WAITING on open sessions: %s" % ", ".join(waiting))
    print("Close them, then run again before the till is reopened.")
if not APPLY:
    print("DRY RUN -- nothing was written. Run again with APPLY=1 to apply.")
    env.cr.rollback()
elif not waiting:
    print("Done: every register has one online method, Online Payment.")
print("=" * 76)
