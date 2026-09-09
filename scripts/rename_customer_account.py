"""Rename the "Customer Account" payment method to "Customer Credit".

    venv/Scripts/python.exe odoo/odoo-bin shell -c odoo.conf -d <db> --no-http \
        < custom_addons/pos_retail/scripts/rename_customer_account.py

On the server:
    sudo -u odoo /opt/odoo/venv/bin/python3 /opt/odoo/odoo/odoo-bin shell \
        -c /etc/odoo/odoo.conf -d ostore_live --no-http \
        < /opt/odoo/custom_addons/pos_retail/scripts/rename_customer_account.py

"Customer Account" is Odoo's phrase for taking payment later. At this
counter the thing itself is called credit -- udhaar on the khata -- and the
button a cashier presses should say what the shop says.

Safe to rename: nothing keys off the name. The credit limit check, the khata
ledger and the Unpaid (Khata) column all test payment_method_id.type ==
'pay_later', which is unchanged. Past orders keep pointing at the same
record, so old receipts reprint with the new wording too -- correct, since it
is the same method it always was.

Renames every method of type pay_later, whatever it is currently called, so
a branch commissioned later from a renamed model stays consistent. Idempotent.
"""

NEW_NAME = "Customer Credit"

Method = env['pos.payment.method'].sudo().with_context(active_test=False)

renamed, already, blocked = [], [], []
for method in Method.search([]):
    if method.type != 'pay_later':
        continue
    if method.name == NEW_NAME:
        already.append(method)
        continue
    # point_of_sale refuses to modify a payment method that an OPEN session
    # is using, and rightly: a till already holding that button in memory
    # would disagree with the database mid-shift. Reported rather than
    # crashed, because "close the till first" is the actual instruction.
    if method.open_session_ids:
        blocked.append((method.name, method.company_id.name,
                        method.open_session_ids.mapped('name')))
        continue
    renamed.append((method.name, method.company_id.name))
    method.name = NEW_NAME

env.cr.commit()

print()
print("=" * 74)
print("PAY-LATER PAYMENT METHODS")
print("=" * 74)
for old_name, company in renamed:
    print("  [RENAMED] %-22r -> %r   (%s)" % (old_name, NEW_NAME, company))
for method in already:
    print("  [OK]      already %r   (%s)" % (NEW_NAME, method.company_id.name))
for old_name, company, sessions in blocked:
    print("  [BLOCKED] %-22r (%s)" % (old_name, company))
    print("            a session is still open: %s" % ", ".join(sessions))
    print("            close the till, then run this again")
if not renamed and not already and not blocked:
    print("  no pay-later method found -- nothing to rename")

print()
print("Reload any open till (close and reopen the browser tab): the payment")
print("buttons are cached in the running session.")
