"""Stop a parent company from trading, without rewriting what it already sold.

    venv/Scripts/python.exe odoo/odoo-bin shell -c odoo.conf -d <db> --no-http \
        < custom_addons/pos_retail/scripts/retire_parent_register.py

On the server:
    sudo -u odoo /opt/odoo/venv/bin/python3 /opt/odoo/odoo/odoo-bin shell \
        -c /etc/odoo/odoo.conf -d ostore_live --no-http \
        < /opt/odoo/custom_addons/pos_retail/scripts/retire_parent_register.py

This clears what check_branch_setup.py reports as "<parent> sells nothing":
a register sitting on the holding company, which in this architecture should
hold the legal identity only -- chart of accounts, NTN, taxes -- while every
shop is an equal branch owning its own catalogue, customers and takings.

It ARCHIVES the register. It does not delete it, and it does not touch a
single order.

That is the whole point. A parent register usually has real sales behind it,
rung up before the branch structure existed, and those orders are a record of
money that actually changed hands. Moving them into a branch would mean
rewriting the company on posted accounting entries, stock moves and sequence
numbers -- an accountant's decision with a real chance of corrupting stock
valuation, not something a script should do quietly. Archiving stops the NEXT
sale from landing in the wrong company and leaves the past where it happened.

The check counts ACTIVE registers, so archiving is all it takes to pass.

A register with an OPEN session is left alone and reported: closing a till is
a cash-counting exercise someone has to do at the counter, not a side effect
of running a script.

READ ONLY until APPLY is set to True below.
"""

APPLY = False

Config = env['pos.config'].sudo().with_context(active_test=False)
Session = env['pos.session'].sudo()
Order = env['pos.order'].sudo()
Company = env['res.company'].sudo()

archived_count = 0
blocked_count = 0

parents = Company.search([('child_ids', '!=', False)])
if not parents:
    print("no parent companies -- nothing to retire")

for parent in parents:
    registers = Config.search([('company_id', '=', parent.id), ('active', '=', True)])
    print()
    print("=" * 78)
    print("%s%s" % (parent.name, "" if APPLY else "   (DRY RUN -- nothing written)"))
    print("=" * 78)
    if not registers:
        print("  no active register -- already retired, nothing to do")
        continue

    for config in registers:
        orders = Order.search([('config_id', '=', config.id)])
        open_sessions = Session.search([
            ('config_id', '=', config.id), ('state', '!=', 'closed')])
        total = sum(orders.mapped('amount_total'))

        print("  register %r" % config.name)
        print("      history  : %s order(s), %s in total -- KEPT, untouched"
              % (len(orders), round(total, 2)))

        if open_sessions:
            blocked_count += 1
            print("      BLOCKED  : %s session(s) still open (%s)."
                  % (len(open_sessions), ', '.join(open_sessions.mapped('name'))))
            print("                 Close the till properly first -- counting the")
            print("                 cash is a person's job, not a script's.")
            print("                 In Odoo: Point of Sale > Orders > Sessions,")
            print("                 open that session and close it.")
            continue

        if APPLY:
            config.active = False
            archived_count += 1
            print("      done     : archived. New sales can no longer land here.")
        else:
            print("      would    : archive this register. Nothing else changes.")

if APPLY:
    env.cr.commit()
    print()
    # Saying "Written" after archiving nothing -- which an earlier version did
    # when every register was blocked by an open session -- reads as success
    # and sends someone off to re-run the check wondering why it still fails.
    if archived_count:
        print("Archived %s register(s). Re-run check_branch_setup.py to confirm."
              % archived_count)
    if blocked_count:
        print("NOTHING was archived for %s register(s): a session is still open."
              % blocked_count)
        print("Close it at the till, then run this again.")
    if not archived_count and not blocked_count:
        print("Nothing needed changing.")
else:
    print()
    print("=" * 78)
    print("Nothing was written. Set APPLY = True near the top to carry this out,")
    print("or pipe it through sed if you would rather not edit the file:")
    print("  sed 's/^APPLY = False/APPLY = True/' <this file> | odoo-bin shell ...")
    print("=" * 78)
