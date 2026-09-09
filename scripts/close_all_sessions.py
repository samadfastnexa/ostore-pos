"""Close every open till session, so the setup scripts stop being blocked.

    venv/Scripts/python.exe odoo/odoo-bin shell -c odoo.conf -d <db> --no-http \
        < custom_addons/pos_retail/scripts/close_all_sessions.py

On the server:
    sudo -u odoo /opt/odoo/venv/bin/python3 /opt/odoo/odoo/odoo-bin shell \
        -c /etc/odoo/odoo.conf -d ostore_live --no-http \
        < /opt/odoo/custom_addons/pos_retail/scripts/close_all_sessions.py

READ THIS BEFORE SETTING APPLY = True.

Closing a till is normally a cash count: somebody opens the drawer, counts
what is in it, and Odoo records the difference between that and what it
expected. This script does NOT count anything. It declares the counted cash
to be exactly what Odoo expects, so every session closes with a difference
of ZERO.

That is right for a session nobody is really using -- one left open for days,
or a register that should never have been trading -- and WRONG for a real
drawer, where it throws away a discrepancy that is worth knowing about. If
the drawer exists and holds money somebody is accountable for, close it in
the interface instead: Point of Sale > Orders > Sessions.

Two kinds of session are handled differently, because they are different:

  never used   opening_control with no orders at all. Deleted, not closed --
               it recorded nothing, and a closed empty session is just
               clutter in the session list.
  used         everything else. Closed with the expected figure, keeping all
               its orders and its accounting.

A session with DRAFT orders is refused by Odoo and reported here: an
unfinished sale has to be paid or cancelled by a person first.
"""

APPLY = False

Session = env['pos.session'].sudo()
Order = env['pos.order'].sudo()

open_sessions = Session.search([('state', '!=', 'closed')], order='id')

print()
print("=" * 78)
print("OPEN SESSIONS" + ("" if APPLY else "   (DRY RUN -- nothing written)"))
print("=" * 78)

if not open_sessions:
    print("  none -- nothing to do")

deleted, closed, refused = [], [], []

for session in open_sessions:
    orders = Order.search([('session_id', '=', session.id)])
    drafts = orders.filtered(lambda o: o.state == 'draft')
    total = sum(orders.mapped('amount_total'))

    print()
    print("  %s   (%s)" % (session.name or '/', session.config_id.name))
    print("      state=%s  orders=%s  total=%s  opening cash=%s"
          % (session.state, len(orders), round(total, 2),
             session.cash_register_balance_start))

    if drafts:
        refused.append(session)
        print("      REFUSED: %s unfinished order(s). Odoo will not close a"
              % len(drafts))
        print("               session with draft orders -- pay or cancel them first.")
        continue

    if session.state == 'opening_control' and not orders:
        print("      never used: will be DELETED rather than closed")
        if APPLY:
            # Read the name BEFORE unlinking. Reading it afterwards raises
            # "Record does not exist or has been deleted", which a first
            # version then reported as a failed delete -- while the delete
            # had in fact succeeded. A cosmetic bug that told the operator
            # the opposite of the truth.
            label = session.name or '/'
            try:
                with env.cr.savepoint():
                    session.unlink()
                deleted.append(label)
            except Exception as exc:
                print("      could not delete: %s" % str(exc)[:90])
        continue

    expected = session.cash_register_balance_end
    print("      will close, declaring counted cash = %s (expected), so the"
          % expected)
    print("      recorded difference is zero")
    if APPLY:
        try:
            with env.cr.savepoint():
                session.cash_register_balance_end_real = expected
                session.action_pos_session_closing_control()
            session.invalidate_recordset()
            if session.state == 'closed':
                closed.append(session.name)
            else:
                print("      did NOT reach closed -- state is %s. Finish it in the"
                      % session.state)
                print("      interface: Point of Sale > Orders > Sessions.")
        except Exception as exc:
            print("      failed: %s" % str(exc)[:140])

if APPLY:
    env.cr.commit()

print()
print("=" * 78)
if APPLY:
    print("deleted %s never-used session(s): %s" % (len(deleted), deleted or '-'))
    print("closed  %s session(s): %s" % (len(closed), closed or '-'))
    if refused:
        print("refused %s with unfinished orders: %s"
              % (len(refused), refused.mapped('name')))
    still = Session.search_count([('state', '!=', 'closed')])
    print("open sessions remaining: %s" % still)
else:
    print("Nothing was written. Read the warning at the top of this file, then")
    print("set APPLY = True, or pipe it:")
    print("  sed 's/^APPLY = False/APPLY = True/' <this file> | odoo-bin shell ...")
print("=" * 78)
