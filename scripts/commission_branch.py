"""Commission a branch so it can actually trade.

A branch created in the UI is an empty legal shell: no journals, so no payment
methods, so no register, so no way to open a till. This builds the missing
layer by mirroring a branch that already works, rather than inventing a
configuration from scratch.

Journals are created against the PARENT's chart of accounts. That is the one
inheritance the branch architecture keeps on purpose: one business files one
tax return from one chart, while each shop keeps its own catalogue, customers,
takings and expenses. account.account uses check_company_domain_parent_of in
core, so a branch may legitimately post to its parent's accounts.

TWO BUGS THIS SCRIPT EXISTS TO NOT REPEAT:

  * hr.employee.company_id is a STORED RELATED field to resource_id.company_id.
    A batch write over a recordset reported success and changed nothing. Each
    employee is now written individually, the underlying resource is written
    too, and the result is re-read. Reporting "moved" for records that did not
    move is worse than failing.

  * Once the parent stops trading it owns nothing, so any user whose DEFAULT
    company is the parent lands in an empty session where half the interface
    cannot read what it references. That reaches the user as "Access Error" on
    login. Users are moved to a trading branch at the end.

Run with:
    venv/Scripts/python.exe odoo/odoo-bin shell -c odoo.conf -d <db> --no-http \
        < custom_addons/pos_retail/scripts/commission_branch.py
"""

TARGET_COMPANY_ID = 3      # the branch to commission
MODEL_COMPANY_ID = 1       # the company whose register to copy the shape of
MOVE_EMPLOYEES = True
FIX_USER_DEFAULT_COMPANY = True
DRY_RUN = True

dst = env['res.company'].sudo().browse(TARGET_COMPANY_ID)
model_co = env['res.company'].sudo().browse(MODEL_COMPANY_ID)

Journal = env['account.journal'].sudo()
Method = env['pos.payment.method'].sudo()
Config = env['pos.config'].sudo()
Employee = env['hr.employee'].sudo()
PickingType = env['stock.picking.type'].sudo()
Warehouse = env['stock.warehouse'].sudo()
User = env['res.users'].sudo()

problems = []


def verify(label, condition, detail=""):
    if condition:
        print("    verified: %s %s" % (label, detail))
    else:
        problems.append("%s %s" % (label, detail))
        print("    *** NOT VERIFIED: %s %s" % (label, detail))


print("=" * 76)
print("COMMISSION BRANCH  %s   modelled on %s   %s"
      % (dst.name, model_co.name, "(DRY RUN)" if DRY_RUN else "(WRITING)"))
print("=" * 76)

model_cfg = Config.with_context(active_test=False).search(
    [('company_id', '=', model_co.id)], limit=1)
if not model_cfg:
    raise UserError("%s has no register to copy the shape of." % model_co.name)
print("\n  model register: %s   methods: %s"
      % (model_cfg.name, model_cfg.payment_method_ids.mapped('name')))

# --- 1. journals -------------------------------------------------------------
print("\n[1] Journals")
wanted = [(pm.journal_id.name, pm.journal_id.type, pm.journal_id.code)
          for pm in model_cfg.payment_method_ids if pm.journal_id]
if model_cfg.invoice_journal_id:
    wanted.append((model_cfg.invoice_journal_id.name,
                   model_cfg.invoice_journal_id.type,
                   model_cfg.invoice_journal_id.code))
print("    needed: %s" % [w[0] for w in wanted])

def named_for_destination(name):
    """Carry the model's journal NAME across, but not its branch's name.

    Copying verbatim gave the new branch a journal called "Cash Murshid
    Bahria Branch" -- a second shop's till pointing at something named after
    the first, which reads as a mistake in every accounting report it ever
    appears in. Journals with a generic name ("Sales", "Bank") are left alone.

    Both the company AND the register name are checked, because a cash
    journal is usually named after the REGISTER, and the two are not
    reliably spelled the same: on the live database the company is "Murshad
    Bahria Branch" while its register and journal say "Murshid". Matching
    only the company name silently did nothing there.
    """
    for source in (model_co.name, model_cfg.name):
        if source and source in name:
            return name.replace(source, dst.name)
    return name


journals = {}
for name, jtype, code in wanted:
    target_name = named_for_destination(name)
    existing = Journal.search(
        [('company_id', '=', dst.id), ('name', 'in', (target_name, name))], limit=1)
    if existing:
        journals[name] = existing
        continue
    if DRY_RUN:
        if target_name != name:
            print("    %r will be created here as %r" % (name, target_name))
        continue
    # Journal codes are unique per company, so the model's code can be reused.
    journals[name] = Journal.create({
        'name': target_name, 'type': jtype, 'code': code, 'company_id': dst.id,
    })
if not DRY_RUN:
    verify("journals", len(journals) == len(set(w[0] for w in wanted)),
           "%s created/found" % len(journals))

# --- 2. payment methods ------------------------------------------------------
print("\n[2] Payment methods")
methods = Method.browse()
if not DRY_RUN:
    for pm in model_cfg.payment_method_ids:
        existing = Method.search([('company_id', '=', dst.id), ('name', '=', pm.name)], limit=1)
        if existing:
            methods |= existing
            continue
        vals = {
            'name': pm.name,
            'company_id': dst.id,
            'is_cash_count': pm.is_cash_count,
            'split_transactions': pm.split_transactions,
        }
        if pm.journal_id:
            vals['journal_id'] = journals[pm.journal_id.name].id
        methods |= Method.create(vals)
    verify("payment methods", len(methods) == len(model_cfg.payment_method_ids),
           "%s: %s" % (len(methods), methods.mapped('name')))
else:
    print("    would create: %s" % model_cfg.payment_method_ids.mapped('name'))

# --- 3. the register ---------------------------------------------------------
print("\n[3] Register")
cfg = Config.search([('company_id', '=', dst.id), ('active', '=', True)], limit=1)
if cfg:
    print("    exists: %s" % cfg.name)
elif not DRY_RUN:
    inv_j = journals.get(model_cfg.invoice_journal_id.name) if model_cfg.invoice_journal_id else None
    vals = {
        'name': "%s Register" % dst.name,
        'company_id': dst.id,
        'payment_method_ids': [(6, 0, methods.ids)],
    }
    if inv_j:
        vals['invoice_journal_id'] = inv_j.id
        vals['journal_id'] = inv_j.id
    # Without this the new till opens fine and then fails the first time
    # anyone discounts anything: a discount is rung up as a line on a
    # product, and a register with no discount_product_id has nothing to
    # write it onto. The error a cashier sees blames the product's flags,
    # which sends you looking in the wrong place entirely. The product is
    # shared across companies, so the model register's one is reusable.
    discount_product = model_cfg.discount_product_id or env.ref(
        'pos_discount.product_product_consumable', raise_if_not_found=False)
    if discount_product:
        vals['discount_product_id'] = discount_product.id

    # Stock has to leave the NEW branch's warehouse. Left to its own devices
    # a fresh register defaults to whichever picking type comes first, which
    # on this database is the PARENT's "Cash & Carry: PoS Orders" -- so every
    # sale would move goods out of a warehouse the shop does not own, and
    # carry the valuation with it. Worse than the journal version of this bug,
    # and silent.
    def pos_picking_for(company):
        return PickingType.search([
            ('company_id', '=', company.id), ('code', '=', 'outgoing'),
            ('name', 'ilike', 'pos')], limit=1) or PickingType.search([
            ('company_id', '=', company.id), ('code', '=', 'outgoing')], limit=1)

    own_picking = pos_picking_for(dst)
    if not own_picking:
        # A company created in the UI does not necessarily come with a
        # warehouse, and without one it has no picking types, and the register
        # then silently borrows the parent's. A shop that holds stock needs
        # its own warehouse anyway -- the whole architecture rests on each
        # branch owning its own goods -- so make it rather than warn and
        # leave the till wired into someone else's shelves.
        code = ''.join(ch for ch in dst.name.upper() if ch.isalnum())[:5] or 'WH'
        suffix = 1
        while Warehouse.with_context(active_test=False).search_count(
                [('code', '=', code)]):
            suffix += 1
            code = '%s%s' % (code[:4], suffix)
        warehouse = Warehouse.create({
            'name': '%s Warehouse' % dst.name, 'code': code, 'company_id': dst.id,
        })
        own_picking = pos_picking_for(dst)
        print("    created warehouse %r (code %s) so stock leaves this branch's"
              % (warehouse.name, code))
        print("    own shelves rather than the parent's")

    if own_picking:
        vals['picking_type_id'] = own_picking.id
    else:
        print("    WARNING: %s still has no outgoing picking type. The register"
              % dst.name)
        print("             would fall back to another company's -- check the")
        print("             warehouse before trading.")

    # Shop policy the model register carries and a bare one does not.
    # module_pos_hr is the important one: with it off there is no cashier
    # selection and no PIN prompt at all, which is the entire way anyone gets
    # into a till here. The rest are this shop's own limits and layout.
    for fname in ('module_pos_hr', 'only_round_cash_method',
                  'pos_retail_max_percentage_discount',
                  'pos_retail_max_roundoff_amount',
                  'pos_retail_receipt_style'):
        if fname in model_cfg._fields:
            vals[fname] = model_cfg[fname]

    cfg = Config.create(vals)
    # A register that cannot load a product cannot sell anything, so prove it.
    loadable = env['product.template'].sudo().search_count(
        env['product.template']._load_pos_data_domain({}, cfg))
    verify("register created", bool(cfg) and loadable > 0,
           "%s, %s products loadable" % (cfg.name, loadable))
else:
    print("    would be created")

# --- 4. staff ----------------------------------------------------------------
print("\n[4] Staff")
# Employees linked to a user are left alone: moving one to a company its user
# cannot access is refused by res.partner.
movable = Employee.search([('company_id', '=', model_co.id), ('user_id', '=', False)])
if MOVE_EMPLOYEES:
    # Said plainly: this TAKES them off the model branch. That is right when
    # commissioning the first branch out of a parent that is being retired,
    # and wrong when adding a second shop beside one already trading, which
    # would leave the working shop with nobody able to open its till.
    print("    cashiers to MOVE OFF %s: %s"
          % (model_co.name, movable.mapped('name') or 'none'))
else:
    # Reporting "cashiers to move" while MOVE_EMPLOYEES is False, as an
    # earlier version did, describes something that is not going to happen --
    # and the thing it describes is destructive, so being wrong about it in
    # a dry run is how someone applies a change they thought they had refused.
    print("    MOVE_EMPLOYEES is off, so nobody is moved. %s keeps: %s"
          % (model_co.name, movable.mapped('name') or 'none'))
    print("    %s will need its own staff added separately." % dst.name)
if not DRY_RUN and MOVE_EMPLOYEES and movable:
    moved, stuck = [], []
    for emp in movable:
        # company_id is a stored related field to resource_id.company_id; a
        # batch write over the recordset does not stick. Write both, one at a
        # time, and re-read.
        emp.write({'company_id': dst.id})
        if emp.resource_id:
            emp.resource_id.write({'company_id': dst.id})
        emp.invalidate_recordset()
        (moved if emp.company_id == dst else stuck).append(emp.name)
    verify("employees moved", not stuck,
           "%s moved%s" % (len(moved), (", STUCK: %s" % stuck) if stuck else ""))

# --- 5. nobody should default into a company that does not trade -------------
print("\n[5] User default companies")
non_trading = env['res.company'].sudo().browse()
for c in env['res.company'].sudo().search([]):
    has_reg = Config.search_count([('company_id', '=', c.id), ('active', '=', True)])
    has_prod = env['product.template'].sudo().search_count([('company_id', '=', c.id)])
    if not has_reg and not has_prod and env['res.company'].sudo().search_count([('parent_id', '=', c.id)]):
        non_trading |= c
stranded = User.search([('company_id', 'in', non_trading.ids), ('active', '=', True),
                        ('share', '=', False)]) if non_trading else User.browse()
print("    non-trading companies: %s" % (non_trading.mapped('name') or "none"))
print("    users defaulting into one: %s" % (stranded.mapped('login') or "none"))
if not DRY_RUN and FIX_USER_DEFAULT_COMPANY and stranded:
    for u in stranded:
        target = (u.company_ids - non_trading)[:1] or dst
        if target and target not in u.company_ids:
            u.write({'company_ids': [(4, target.id)]})
        u.write({'company_id': target.id})
        u.invalidate_recordset()
        print("      %s -> %s" % (u.login, u.company_id.name))
    stranded.invalidate_recordset()
    verify("users rehomed", all(u.company_id not in non_trading for u in stranded),
           "(%s users)" % len(stranded))

print("\n" + "=" * 76)
if DRY_RUN:
    env.cr.rollback()
    print("DRY RUN complete, nothing written. Set DRY_RUN = False to apply.")
elif problems:
    env.cr.rollback()
    print("ROLLED BACK -- %s step(s) could not be verified:" % len(problems))
    for p in problems:
        print("  - %s" % p)
else:
    env.cr.commit()
    print("Committed, every step verified.")
print("=" * 76)
