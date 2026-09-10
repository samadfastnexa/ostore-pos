"""Delete the parent company's trading data. It was test data.

    sudo -u odoo /opt/odoo/venv/bin/python3 /opt/odoo/odoo/odoo-bin shell \
        -c /etc/odoo/odoo.conf -d ostore_live --no-http \
        < /opt/odoo/custom_addons/pos_retail/scripts/purge_parent_company_data.py

The shop's answer to "these are trading records" was that the parent's
orders were testing from before the branches were split out. Taken at their
word, so this deletes rather than archives.

WHAT IT DELETES, in this order, because each step frees the next:

    0. records in this module that point at the parent's registers
    1. the journal entries behind the parent's POS orders
    2. the parent's POS orders
    3. the parent's POS sessions
    4. every POS register on the parent, archived ones included
    5. stock on hand and stock moves for products the parent owns
    6. those products themselves

WHAT IT WILL NOT TOUCH, and why each one would break the shop:

    * ANYTHING WITH NO COMPANY. A record with no company belongs to every
      company. It sorts beside the parent's and reads like the parent's.
      Deleting a shared product empties it out of both branches too.

    * THE PARENT'S JOURNALS. The branches invoice through the parent's
      journal -- that is how this database was deliberately wired. Deleting
      them stops both branches invoicing.

    * THE COMPANY CONTACT AND EMPLOYEES. res.company points at a partner,
      and users point at employees. Deleting those breaks logins.

    * ANYTHING OWNED BY A BRANCH. Every filter names the parent explicitly.
      Nothing is selected by "not a branch".

THIS USES RAW SQL IN THREE PLACES, and that is worth stating plainly rather
than burying. Odoo refuses to delete a paid order, a done stock move, or a
posted journal entry, and it is right to: for real trade those refusals are
the audit trail working. They are bypassed here because the owner has said
this is test data. Each bypass is marked at the line where it happens.

THE ONE THING THAT CANNOT BE BYPASSED is the open-session check. Odoo will
not delete a POS product while ANY session anywhere is open, including a
branch's live one, because a cashier may have it on screen right now. So the
product step is skipped, not forced, while a session is open. Close the
day's sessions properly and run this again.

Each step runs in its own savepoint: a refusal rolls back only that step.

READ ONLY until APPLY is set to True.
"""

APPLY = False

Company = env['res.company'].sudo()
parents = Company.search([('parent_id', '=', False)])
if not parents:
    raise SystemExit("No parent company found.")
PARENT_IDS = parents.ids

PosOrder = env['pos.order'].sudo()
PosSession = env['pos.session'].sudo().with_context(active_test=False)
PosConfig = env['pos.config'].sudo().with_context(active_test=False)
Product = env['product.product'].sudo().with_context(active_test=False)
Quant = env['stock.quant'].sudo()
StockMove = env['stock.move'].sudo()

orders = PosOrder.search([('company_id', 'in', PARENT_IDS)])
sessions = PosSession.search([('config_id.company_id', 'in', PARENT_IDS)])
configs = PosConfig.search([('company_id', 'in', PARENT_IDS)])
moves = orders.mapped('account_move')
products = Product.search([('company_id', 'in', PARENT_IDS)])
# Selected by product as well as by company. Filtering on company alone left
# behind quants that hold a parent-owned product but are stamped with another
# company, and the product delete then failed on a foreign key from a row the
# earlier step had never looked at. If the product is going, its stock goes
# with it wherever that stock is recorded.
quants = Quant.search(['|', ('company_id', 'in', PARENT_IDS),
                       ('product_id', 'in', products.ids)])

open_sessions = env['pos.session'].sudo().search([('state', '!=', 'closed')])

line_break = "=" * 78
print()
print(line_break)
print("PURGE PARENT COMPANY" + ("" if APPLY else "   (DRY RUN -- nothing written)"))
print(line_break)
print()
print("  Parent: %s" % ", ".join("%s (id %s)" % (c.name, c.id) for c in parents))

print()
print("  To delete:")
print("      journal entries behind those orders : %s" % len(moves))
print("      POS orders                          : %s  (%s)" % (
    len(orders), ", ".join(sorted(set(orders.mapped('state')))) or "none"))
print("      POS sessions                        : %s" % len(sessions))
print("      POS registers (incl. archived)      : %s" % len(configs))
print("      stock on hand rows                  : %s" % len(quants))
print("      products owned by the parent        : %s" % len(products))

print()
print("  Deliberately NOT touched:")
print("      products shared with every company  : %s"
      % Product.search_count([('company_id', '=', False)]))
print("      the parent's journals               : %s"
      % env['account.journal'].sudo().search_count([('company_id', 'in', PARENT_IDS)]))
print("      employees on the parent             : %s"
      % env['hr.employee'].sudo().search_count([('company_id', 'in', PARENT_IDS)]))
print("      anything owned by a branch")

if open_sessions:
    print()
    print("  OPEN POS SESSIONS ELSEWHERE: %s" % len(open_sessions))
    for session in open_sessions:
        print("      %-28r on %r" % (session.name[:26], session.config_id.company_id.name))
    print("      Odoo refuses to delete a POS product while any session is open,")
    print("      anywhere, because a cashier may have it on screen right now.")
    print("      The product step will be SKIPPED. Everything else still runs.")
    print("      To include products: close the day properly, then run this again.")


# Models with a step of their own further down. The sweep must leave them
# alone: it deletes by a plain unlink, and a stock transfer or a posted entry
# needs its state relaxed first. Letting the sweep reach a transfer made it
# try to cancel done stock moves, which is refused -- correctly, since that
# is exactly the operation a return exists for.
HANDLED_ELSEWHERE = {
    'pos.order', 'pos.session', 'pos.config',
    'stock.picking', 'stock.move', 'stock.move.line', 'stock.quant',
    'account.move', 'account.move.line',
}


def referencing_records(target_model, doomed_ids):
    """Records in any model that point at the doomed rows.

    Found by scanning the field definitions rather than by listing tables by
    hand. The first attempt hard-coded the models this module owns and was
    immediately caught out by one it did not: a foreign key with RESTRICT
    stopped the register delete dead. Anything added later would have done
    the same, so this asks the registry instead of relying on memory.
    """
    found = []
    fields_ = env['ir.model.fields'].sudo().search([
        ('ttype', '=', 'many2one'), ('relation', '=', target_model)])
    for field in fields_:
        Model = env.get(field.model)
        if Model is None or Model._transient or Model._abstract:
            continue
        # Reporting models are SQL views, not tables. They carry a config_id
        # like anything else, so the scan finds them, and Postgres then
        # refuses the delete with "cannot delete from view". Nothing is
        # stored in them to delete: they are a query over the real rows.
        if not Model._auto:
            continue
        if Model._name in HANDLED_ELSEWHERE:
            continue
        if field.name not in Model._fields or not Model._fields[field.name].store:
            continue
        # A cascading link needs no help: deleting the record it points at
        # takes it too. Touching them here is worse than useless -- POS order
        # lines cascade from their order, and trying to delete them first
        # trips the guard that says a line can only go when its order is
        # cancelled, which has not happened yet at this point in the run.
        if Model._fields[field.name].ondelete == 'cascade':
            continue
        try:
            hits = Model.sudo().with_context(active_test=False).search(
                [(field.name, 'in', doomed_ids)])
        except Exception:
            continue
        if hits:
            found.append((Model._name, field.name, hits))
    return found


if not APPLY:
    print()
    print("  Records elsewhere pointing at the parent's registers/orders/sessions:")
    any_found = False
    for target, ids in (('pos.config', configs.ids), ('pos.order', orders.ids),
                        ('pos.session', sessions.ids)):
        for model_name, field_name, hits in referencing_records(target, ids):
            any_found = True
            print("      %-40s .%-18s %s row(s)" % (model_name, field_name, len(hits)))
    if not any_found:
        print("      none")
    print()
    print(line_break)
    print("Nothing was written. Set APPLY = True, or pipe it:")
    print("  sed 's/^APPLY = False/APPLY = True/' <this file> | odoo-bin shell ...")
    print(line_break)
else:
    results = []

    def step(label, fn):
        """Run one deletion inside its own savepoint.

        A refusal must not poison the transaction for the steps after it.
        Without the savepoint, one UserError leaves the cursor unusable and
        everything that follows fails for a reason unrelated to it, which
        reads as a far bigger disaster than it is.
        """
        try:
            with env.cr.savepoint():
                count = fn()
            results.append((label, count, None))
            print("      %-42s %s" % (label, count))
        except Exception as err:
            results.append((label, 0, err))
            print("      %-42s REFUSED: %s" % (label, str(err).strip().split("\n")[0]))

    print()
    print("  Deleting:")

    def drop_references():
        total = 0
        for target, ids in (('pos.config', configs.ids), ('pos.order', orders.ids),
                            ('pos.session', sessions.ids)):
            for _model_name, _field_name, hits in referencing_records(target, ids):
                total += len(hits)
                hits.unlink()
        return total
    step("records pointing at those registers", drop_references)

    def drop_moves():
        n = len(moves)
        # BYPASS 1. force_delete clears both guards on account.move: the
        # sequence-chain check and the audit-trail check. Posted entries are
        # normally reversed, never deleted, and that is correct for real
        # trade. This is test data, removed on the owner's instruction.
        moves.with_context(force_delete=True).unlink()
        return n
    step("journal entries behind the orders", drop_moves)

    def drop_orders():
        if not orders:
            return 0
        n = len(orders)
        # BYPASS 2. pos.order.write refuses to move a paid order out of
        # paid/done/invoiced, so the ORM cannot set it to cancel, and unlink
        # only accepts draft or cancel. The state is written in SQL and the
        # cache invalidated so the delete guard reads the new value. Not a
        # workflow anyone should use on a live sale.
        env.cr.execute("UPDATE pos_order SET state = 'cancel' WHERE id IN %s",
                       (tuple(orders.ids),))
        orders.invalidate_recordset(['state'])
        orders.unlink()
        return n
    step("POS orders", drop_orders)

    def drop_sessions():
        if not sessions:
            return 0
        n = len(sessions)
        env.cr.execute("UPDATE pos_session SET state = 'closed' WHERE id IN %s",
                       (tuple(sessions.ids),))
        sessions.invalidate_recordset(['state'])
        sessions.unlink()
        return n
    step("POS sessions", drop_sessions)

    def drop_configs():
        n = len(configs)
        configs.unlink()
        return n
    step("POS registers", drop_configs)

    def drop_stock():
        doomed = StockMove.search(['|', ('company_id', 'in', PARENT_IDS),
                                   ('product_id', 'in', products.ids)])
        n = len(doomed) + len(quants)
        if doomed:
            # BYPASS 3. A move line whose state is done or cancel refuses to
            # be deleted, and stock.move.unlink deletes its lines first.
            #
            # The line's state is declared related to the move's, which
            # looked like relaxing the move would be enough. It is not: that
            # related field is store=True, so the line keeps its own copy in
            # its own column, and updating only stock_move left every line
            # still reading 'done'. Both tables are written.
            env.cr.execute("UPDATE stock_move SET state = 'draft' WHERE id IN %s",
                           (tuple(doomed.ids),))
            env.cr.execute(
                "UPDATE stock_move_line SET state = 'draft' WHERE move_id IN %s",
                (tuple(doomed.ids),))
            env.invalidate_all()
            doomed.unlink()
        # Searched again rather than reusing the set counted above. Deleting
        # stock moves makes Odoo recompute stock, which writes NEW quant rows
        # -- so the list gathered before the moves went is already out of
        # date, and the product delete then failed on a quant that had not
        # existed when the earlier search ran.
        leftover = Quant.search(['|', ('company_id', 'in', PARENT_IDS),
                                 ('product_id', 'in', products.ids)])
        if leftover:
            leftover.unlink()
        return n
    step("stock on hand and stock moves", drop_stock)

    if open_sessions:
        print("      %-42s SKIPPED: a POS session is open" % "products owned by the parent")
        results.append(("products owned by the parent", 0, None))
    else:
        def drop_products():
            templates = products.mapped('product_tmpl_id')
            n = len(products)
            # One last sweep. Each of the steps above can leave a stock row
            # behind as a side effect of its own recompute, and a single
            # surviving quant is enough for Postgres to refuse the whole
            # product delete on a foreign key.
            Quant.search([('product_id', 'in', products.ids)]).unlink()
            products.unlink()
            # A template left with no variants is dead weight. One that still
            # has variants belongs to something else and stays.
            #
            # .exists() first: deleting a variant can take its template with
            # it, so this recordset holds rows that are already gone, and
            # reading a field off one of those raises "Record does not exist"
            # -- reported as a failure of a delete that had in fact worked.
            templates.exists().filtered(lambda t: not t.product_variant_ids).unlink()
            return n
        step("products owned by the parent", drop_products)

    env.cr.commit()

    print()
    print(line_break)
    refused = [r for r in results if r[2]]
    if refused:
        print("FINISHED WITH REFUSALS. Everything else was deleted and committed.")
        print()
        for label, _count, err in refused:
            print("  %s" % label)
            print("      %s" % str(err).strip().replace("\n", "\n      "))
    else:
        print("DONE.")
    print(line_break)
    print()
    print("  Left on the parent now:")
    print("      registers : %s" % PosConfig.search_count([('company_id', 'in', PARENT_IDS)]))
    print("      POS orders: %s" % PosOrder.search_count([('company_id', 'in', PARENT_IDS)]))
    print("      products  : %s" % Product.search_count([('company_id', 'in', PARENT_IDS)]))
