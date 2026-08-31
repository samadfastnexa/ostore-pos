"""Verify the branch architecture on any database. READ ONLY.

Safe to run against production: it opens no transaction it does not roll back
and writes nothing. Run it after deploying a new version, or any time the
company/branch setup is in doubt.

    venv/Scripts/python.exe odoo/odoo-bin shell -c odoo.conf -d <db> --no-http \
        < custom_addons/pos_retail/scripts/check_branch_setup.py

On the server:
    sudo -u odoo /opt/odoo/venv/bin/python3 /opt/odoo/odoo/odoo-bin shell \
        -c /etc/odoo/odoo.conf -d ostore_live --no-http \
        < /opt/odoo/custom_addons/pos_retail/scripts/check_branch_setup.py

The target shape it checks for: a parent company holding ONLY the legal
identity -- chart of accounts, NTN, taxes -- with every shop an equal branch
owning its own catalogue, customers, khata, till and expenses.
"""

results = []
skipped = []


def check(name, ok, detail="", severity="FAIL"):
    results.append((name, bool(ok), detail, severity))
    print("  [%-4s] %-46s %s" % ("PASS" if ok else severity, name, detail))


Company = env['res.company'].sudo()
Template = env['product.template'].sudo()
Partner = env['res.partner'].sudo()
Config = env['pos.config'].sudo()
Employee = env['hr.employee'].sudo()
Rule = env['ir.rule'].sudo()

roots = Company.search([('parent_id', '=', False)])
branches = Company.search([('parent_id', '!=', False)])

print("=" * 78)
print("BRANCH ARCHITECTURE CHECK   db=%s" % env.cr.dbname)
print("=" * 78)
print("\nSTRUCTURE")
for r in roots:
    print("  %s" % r.name)
    for b in Company.search([('parent_id', '=', r.id)]):
        print("    |- %s" % b.name)
if not branches:
    print("    (no branches -- nothing to separate)")

# --- 1. the record rules that enforce separation -----------------------------
print("\nRECORD RULES")
expected = {
    'res.partner': 'Contacts',
    'product.template': 'Product',
    'product.supplierinfo': 'Vendor Pricelist',
    'product.pricelist': 'Pricelist',
    'pos.retail.expense': 'Expense',
    'pos.category': 'POS Category',
    'product.category': 'Product Category',
    'product.brand': 'Product Brand',
}
for model, label in expected.items():
    if model not in env:
        continue
    r = Rule.search([('model_id.model', '=', model), ('name', 'like', '%own branch%')], limit=1)
    check("rule active: %s" % model, bool(r and r.active),
          "" if (r and r.active) else ("missing" if not r else "INACTIVE"))

# The partner rule must keep core's partner_share clause or staff records
# vanish from every branch and user administration breaks.
pr = Rule.search([('model_id.model', '=', 'res.partner'), ('name', 'like', '%own branch%')], limit=1)
check("partner rule keeps partner_share clause",
      pr and 'partner_share' in (pr.domain_force or ''),
      "" if (pr and 'partner_share' in (pr.domain_force or '')) else "staff would be hidden")

# --- 2. the parent must not trade --------------------------------------------
print("\nPARENT COMPANIES (should hold no operational data)")
for r in roots:
    if not Company.search_count([('parent_id', '=', r.id)]):
        continue  # a company with no branches is just a company
    n_prod = Template.search_count([('company_id', '=', r.id)])
    n_reg = Config.search_count([('company_id', '=', r.id), ('active', '=', True)])
    n_cust = Partner.search_count([('company_id', '=', r.id), ('customer_rank', '>', 0)])
    check("%s sells nothing" % r.name, n_prod == 0 and n_reg == 0,
          "" if (n_prod == 0 and n_reg == 0)
          else "%s products, %s active register(s), %s customers" % (n_prod, n_reg, n_cust))

# --- 3. every branch must be able to trade -----------------------------------
print("\nBRANCHES (each must be able to open a till and sell)")
for b in branches:
    cfg = Config.search([('company_id', '=', b.id), ('active', '=', True)], limit=1)
    loadable = 0
    if cfg:
        try:
            loadable = Template.search_count(Template._load_pos_data_domain({}, cfg))
        except Exception:
            loadable = -1
    emp = Employee.search_count([('company_id', '=', b.id)])
    journals = env['account.journal'].sudo().search_count([('company_id', '=', b.id)])
    ok = bool(cfg) and loadable > 0 and emp > 0 and journals > 0
    check("%s can trade" % b.name, ok,
          "register=%s products=%s staff=%s journals=%s"
          % (cfg.name if cfg else 'NONE', loadable, emp, journals))

# --- 4. the mistake that keeps recurring -------------------------------------
# A partner used by more than one company cannot be owned by one branch: the
# branch rule then denies the referencing company access to its own history,
# which surfaces to the user as a bare "Access Error" on login.
print("\nCROSS-COMPANY REFERENCES (cause of 'Access Error' on login)")
owned = Partner.search([('company_id', '!=', False)])
offenders = []
for model, fields in [('purchase.order', ['partner_id']),
                      ('sale.order', ['partner_id', 'partner_invoice_id', 'partner_shipping_id']),
                      ('pos.order', ['partner_id']),
                      ('account.move', ['partner_id']),
                      ('stock.picking', ['partner_id'])]:
    if model not in env:
        continue
    M = env[model].sudo()
    for f in fields:
        if f not in M._fields:
            continue
        for r in M.search([(f, 'in', owned.ids)]):
            p = r[f]
            if p.company_id and r.company_id and p.company_id != r.company_id:
                offenders.append((p.name, p.company_id.name, model, r.company_id.name))
check("no partner is referenced across companies", not offenders,
      "" if not offenders else "%s offender(s), e.g. '%s' owned by %s used by %s in %s"
      % (len(offenders), offenders[0][0], offenders[0][1], offenders[0][2], offenders[0][3]))
for name, owner, model, user_co in offenders[:8]:
    print("         '%s' owned by %s but used by %s in %s -> must be SHARED"
          % (name[:30], owner, model, user_co))

# Employees hit the same wall and it is easy to miss, because the fix is the
# OPPOSITE one: hr_employee.company_id is NOT NULL, so an employee cannot be
# shared the way a partner can. A cashier who has rung up sales for a company
# must STAY with it, and the branch needs its own employee record for that
# person. Move one and the original company can no longer read its own orders.
emp_offenders = []
Emp = env['hr.employee'].sudo()
owned_emp = Emp.search([('company_id', '!=', False)])
if owned_emp:
    for model in sorted(env.registry.keys()):
        M = env[model]
        if not M._auto or model.startswith(('ir.', 'bus.')) or 'company_id' not in M._fields:
            continue
        for fname, f in M._fields.items():
            if f.type != 'many2one' or f.comodel_name != 'hr.employee' or not f.store:
                continue
            try:
                recs = M.sudo().search([(fname, 'in', owned_emp.ids)])
            except Exception:
                continue
            for r in recs:
                emp = r[fname]
                if emp.company_id and r.company_id and emp.company_id != r.company_id:
                    emp_offenders.append((emp.name, emp.company_id.name, model, r.company_id.name))
check("no employee is referenced across companies", not emp_offenders,
      "" if not emp_offenders else "%s offender(s), e.g. '%s' owned by %s used by %s in %s"
      % (len(emp_offenders), emp_offenders[0][0], emp_offenders[0][1],
         emp_offenders[0][2], emp_offenders[0][3]))
seen_emp = set()
for name, owner, model, user_co in emp_offenders:
    if (name, user_co) in seen_emp:
        continue
    seen_emp.add((name, user_co))
    print("         '%s' owned by %s but used by %s in %s -> must move BACK to %s"
          % (name[:26], owner, model, user_co, user_co))

# --- 5. leaks: does one branch see another's data? ---------------------------
print("\nISOLATION (a branch must not see a sibling's or its parent's records)")
User = env['res.users'].sudo()
for b in branches:
    # Measure through a real user who is actually a member of the branch.
    # Evaluating as superuser would bypass record rules and report a clean
    # result no matter how badly they leaked, which is the one outcome a
    # verification script must never produce.
    tester = User.search([('company_ids', 'in', b.id), ('active', '=', True),
                          ('share', '=', False)], limit=1)
    if not tester:
        skipped.append("%s isolation" % b.name)
        print("  [SKIP] %-46s no user is a member of this branch" % ("%s isolation" % b.name))
        continue
    e = env(user=tester.id, context=dict(env.context, allowed_company_ids=[b.id]))
    seen = e['product.template'].search_count([])
    own = Template.search_count([('company_id', '=', b.id)])
    shared = Template.search_count([('company_id', '=', False)])
    check("%s sees only its own products" % b.name, seen <= own + shared,
          "as %s: sees %s, owns %s (+%s shared)"
          % (tester.login, seen, own, shared))

# --- 5b. a register must be wired entirely inside its own company ------------
# Third class of cross-company leak, found after partners and employees: the
# branch-1 register was created while the shell's active company was the
# parent, so pos.config's DEFAULT picked the parent's PoS picking type -- and
# every user scoped to the branch got "Access Error: Picking Type" on screens
# that touch it. Sweep every stored many2one on every register; create_uid and
# write_uid are audit metadata and exempt.
print(chr(10) + "REGISTER WIRING (every part of a till must belong to its company)")
cfg_bad = []
for c in Config.with_context(active_test=False).search([]):
    for fname, f in c._fields.items():
        if f.type != 'many2one' or not f.store or fname in ('create_uid', 'write_uid'):
            continue
        val = c[fname]
        if val and 'company_id' in val._fields and val.company_id and val.company_id != c.company_id:
            cfg_bad.append((c.name, fname, val.display_name, val.company_id.name))
check("every register is wired inside its own company", not cfg_bad,
      "" if not cfg_bad else "%s: e.g. %s.%s -> %s [%s]"
      % (len(cfg_bad), cfg_bad[0][0], cfg_bad[0][1], cfg_bad[0][2][:24], cfg_bad[0][3]))
for name, fname, disp, co in cfg_bad[:6]:
    print("         %s.%s -> '%s' owned by %s" % (name, fname, disp[:30], co))

# --- 6. nobody should land in a company that does not trade ------------------
# Once the parent stops trading it owns nothing, so a user whose DEFAULT
# company is the parent opens an empty session in which half the interface
# cannot read what it references. That surfaces as "Access Error" on login and
# looks like a broken permission model when it is really a bad landing place.
print("\nUSER DEFAULT COMPANY (a user must land somewhere that trades)")
non_trading = Company.browse()
for c in Company.search([]):
    if not Company.search_count([('parent_id', '=', c.id)]):
        continue
    if not Config.search_count([('company_id', '=', c.id), ('active', '=', True)]) \
            and not Template.search_count([('company_id', '=', c.id)]):
        non_trading |= c
stranded = env['res.users'].sudo().search(
    [('company_id', 'in', non_trading.ids), ('active', '=', True), ('share', '=', False)]
) if non_trading else env['res.users'].browse()
check("no user defaults into a non-trading company", not stranded,
      "" if not stranded else "%s: %s" % (len(stranded), stranded.mapped('login')[:4]))

# --- summary -----------------------------------------------------------------
failed = [r for r in results if not r[1] and r[3] == 'FAIL']
warned = [r for r in results if not r[1] and r[3] == 'WARN']
print("\n" + "=" * 78)
print("%s checks, %s failed, %s warnings, %s skipped" % (len(results), len(failed), len(warned), len(skipped)))
for name in skipped:
    print("  SKIPPED (not verified): %s" % name)
if failed:
    print("\nFAILED:")
    for name, _ok, detail, _sev in failed:
        print("  - %s   %s" % (name, detail))
    print("\nFix before trading. See scripts/copy_catalogue_to_branch.py and")
    print("scripts/commission_branch.py, and the branch rules in")
    print("security/pos_retail_branch_rules.xml.")
else:
    print("\nAll good: the parent holds only the legal identity and every branch can trade.")
print("=" * 78)

env.cr.rollback()
