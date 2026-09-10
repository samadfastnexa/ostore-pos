"""The payments left on the parent company after the POS purge.

    sudo -u odoo /opt/odoo/venv/bin/python3 /opt/odoo/odoo/odoo-bin shell \
        -c /etc/odoo/odoo.conf -d ostore_live --no-http \
        < /opt/odoo/custom_addons/pos_retail/scripts/purge_parent_payments.py

Seven payments survived the purge. Only one was ever attached to a POS
session; the other six were made in the back office, so they were never in
the purge's scope and are shown here to be looked at rather than assumed.

WHY ONE OF THEM REFUSED TO DELETE. account.payment._check_move_id forbids a
payment being in any state but draft or cancelled once its journal entry is
gone, and unlink deletes that entry first. So a live payment has to be
cancelled before it can be removed. Doing that is the point of this script.

THE GUARD THAT MATTERS MOST HERE. This shop's branches invoice through the
PARENT's journals -- that wiring was deliberate. So a payment sitting on a
parent journal is not automatically the parent's own business: it may be
settling a branch's invoice. Deleting it would knock that invoice back to
unpaid and leave the branch's books wrong.

So any payment reconciled against a document belonging to a branch is
refused outright, and named. Only payments that touch nothing, or touch the
parent alone, can go.

READ ONLY until APPLY is set to True.
"""

APPLY = False

Company = env['res.company'].sudo()
Payment = env['account.payment'].sudo()

parents = Company.search([('parent_id', '=', False)])
branches = Company.search([('parent_id', '!=', False)])
payments = Payment.search([('company_id', 'in', parents.ids)])

line_break = "=" * 78
print()
print(line_break)
print("PAYMENTS ON THE PARENT" + ("" if APPLY else "   (DRY RUN -- nothing written)"))
print(line_break)

if not payments:
    print()
    print("  None. Nothing to do.")
else:
    safe, protected = [], []
    for payment in payments:
        # Everything this payment is reconciled against, in either direction.
        touched = payment.reconciled_invoice_ids | payment.reconciled_bill_ids
        branch_docs = touched.filtered(lambda m: m.company_id in branches)
        if branch_docs:
            protected.append((payment, branch_docs))
        else:
            safe.append((payment, touched))

    print()
    print("  %-22s %-12s %10s  %-16s %s" % ("PAYMENT", "STATE", "AMOUNT", "JOURNAL", "PARTNER"))
    for payment in payments:
        print("  %-22s %-12s %10s  %-16s %s" % (
            payment.name or "(unnamed)", payment.state, payment.amount,
            payment.journal_id.name[:16], (payment.partner_id.name or "none")[:24]))

    if protected:
        print()
        print("  REFUSED -- these settle a BRANCH document:")
        for payment, docs in protected:
            print("      %-22s pays %s" % (
                payment.name, ", ".join("%s (%s)" % (m.name, m.company_id.name) for m in docs)))
        print("      Deleting these would knock those invoices back to unpaid.")

    if safe:
        print()
        print("  Can be deleted -- these touch nothing, or the parent only:")
        for payment, touched in safe:
            print("      %-22s %s" % (
                payment.name,
                "reconciled against: " + ", ".join(touched.mapped('name'))
                if touched else "not reconciled against anything"))

    if not APPLY:
        print()
        print(line_break)
        print("Nothing was written. Set APPLY = True, or pipe it:")
        print("  sed 's/^APPLY = False/APPLY = True/' <this file> | odoo-bin shell ...")
        print(line_break)
    else:
        print()
        print("  Deleting:")
        for payment, _touched in safe:
            label = payment.name or str(payment.id)
            try:
                # A savepoint each: one stubborn payment must not roll back
                # the others, and must not poison the cursor for them either.
                with env.cr.savepoint():
                    if payment.state not in ('draft', 'canceled'):
                        # Cancels the payment and disposes of its journal
                        # entry, which is what _check_move_id demands before
                        # the record itself can go.
                        payment.action_cancel()
                    payment.unlink()
                print("      %-22s deleted" % label)
            except Exception as err:
                print("      %-22s REFUSED: %s" % (label, str(err).strip().split("\n")[0]))
        env.cr.commit()
        print()
        print("  Payments left on the parent: %s"
              % Payment.search_count([('company_id', 'in', parents.ids)]))
