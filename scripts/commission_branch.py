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

journals = {}
for name, jtype, code in wanted:
    existing = Journal.search([('company_id', '=', dst.id), ('name', '=', name)], limit=1)
    if existing:
        journals[name] = existing
        continue
    if DRY_RUN:
        continue
    # Journal codes are unique per company, so the model's code can be reused.
    journals[name] = Journal.create({
        'name': name, 'type': jtype, 'code': code, 'company_id': dst.id,
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
print("    cashiers to move: %s" % movable.mapped('name'))
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
