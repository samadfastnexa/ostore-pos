"""The invoices, bills and journal entries left on the parent company.

    sudo -u odoo /opt/odoo/venv/bin/python3 /opt/odoo/odoo/odoo-bin shell \
        -c /etc/odoo/odoo.conf -d ostore_live --no-http \
        < /opt/odoo/custom_addons/pos_retail/scripts/purge_parent_invoices.py

RUN THIS AFTER purge_parent_payments.py. A payment deletes its own journal
entry on the way out, so clearing payments first leaves less here and avoids
this script tripping over an entry that is about to disappear anyway.

The shop has confirmed there is no real customer and no real order on the
parent: it is all test data from before the branches were split out. So
these are deleted rather than reversed.

WHAT ODOO NORMALLY DOES INSTEAD, and why it is being overridden. A posted
entry is meant to be reversed, never deleted, so the numbering has no gaps
and last year's figures cannot silently change. Two guards enforce that --
one on the sequence chain, one on the audit trail -- and both are switched
off here with force_delete. That is right for test data and wrong for real
trade, so this script is not a habit to carry into daily use.

THE GUARD THAT STAYS ON. A parent entry reconciled against a BRANCH document
is refused and named. The branches invoice through the parent's journals by
design, so the two companies' entries genuinely do touch, and deleting one
side would leave a branch invoice pointing at nothing.

WHAT IS NOT TOUCHED: the parent's journals themselves (both branches post
through them), the company contact, employees, and anything owned by a
branch.

READ ONLY until APPLY is set to True.
"""

APPLY = False

Company = env['res.company'].sudo()
Move = env['account.move'].sudo()

parents = Company.search([('parent_id', '=', False)])
branches = Company.search([('parent_id', '!=', False)])
moves = Move.search([('company_id', 'in', parents.ids)])

line_break = "=" * 78
print()
print(line_break)
print("ENTRIES ON THE PARENT" + ("" if APPLY else "   (DRY RUN -- nothing written)"))
print(line_break)


def counterparts(move):
    """Every move this one is reconciled against.

    Reconciliation is what actually ties two companies' books together here,
    and it is not visible from company_id alone: a parent entry can be
    matched line-by-line against a branch's invoice through the shared
    journal. Walking the matched debits and credits is the only way to see
    that link before deleting one end of it.
    """
    lines = move.line_ids
    partials = lines.matched_debit_ids | lines.matched_credit_ids
    other = partials.debit_move_id.move_id | partials.credit_move_id.move_id
    return other - move


if not moves:
    print()
    print("  None. Nothing to do.")
else:
    safe, protected = [], []
    for move in moves:
        linked_branch = counterparts(move).filtered(lambda m: m.company_id in branches)
        if linked_branch:
            protected.append((move, linked_branch))
        else:
            safe.append(move)

    print()
    print("  %s entry/entries on the parent" % len(moves))
    by_type = {}
    for move in moves:
        by_type[move.move_type] = by_type.get(move.move_type, 0) + 1
    for move_type, count in sorted(by_type.items()):
        print("      %-22s %s" % (move_type, count))

    if protected:
        print()
        print("  REFUSED -- reconciled against a BRANCH document:")
        for move, others in protected:
            print("      %-26s ties to %s" % (
                move.name, ", ".join("%s (%s)" % (m.name, m.company_id.name) for m in others)))

    if safe:
        print()
        print("  To delete:")
        for move in safe[:25]:
            print("      %-26s %-14s %-10s %s" % (
                move.name or "(draft)", move.move_type, move.state,
                (move.partner_id.name or "")[:24]))
        if len(safe) > 25:
            print("      ... and %s more" % (len(safe) - 25))

    if not APPLY:
        print()
        print(line_break)
        print("Nothing was written. Set APPLY = True, or pipe it:")
        print("  sed 's/^APPLY = False/APPLY = True/' <this file> | odoo-bin shell ...")
        print(line_break)
    else:
        print()
        print("  Deleting:")
        deleted = failed = 0
        for move in safe:
            label = move.name or "(draft %s)" % move.id
            try:
                # A savepoint each. One entry Odoo will not part with must
                # neither roll back the others nor poison the cursor for
                # them, and with dozens of entries a single shared savepoint
                # would turn one refusal into a total failure.
                with env.cr.savepoint():
                    doomed = move.with_context(force_delete=True)
                    if doomed.state != 'draft':
                        # Reconciliation has to be undone before the entry
                        # will move: a matched line is what the other side of
                        # the match points at.
                        doomed.line_ids.remove_move_reconcile()
                        doomed.button_draft()
                    doomed.unlink()
                deleted += 1
            except Exception as err:
                failed += 1
                print("      %-26s REFUSED: %s" % (label, str(err).strip().split("\n")[0]))
        env.cr.commit()
        print("      deleted %s, refused %s" % (deleted, failed))
        print()
        print("  Entries left on the parent: %s"
              % Move.search_count([('company_id', 'in', parents.ids)]))
