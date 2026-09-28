from . import models
from . import controllers

# The one electronic way to pay at the till. The shop asked for a single
# "Online Payment" instead of separate Card, JazzCash and EasyPaisa buttons:
# the cashier confirms the money arrived, whichever app or bank it came
# through, and it all settles to one bank journal. Cash and Customer Account
# (khata) are separate methods and are not affected.
ONLINE_PAYMENT_NAME = 'Online Payment'
ONLINE_PAYMENT_JOURNAL_CODE = 'ONLN'  # account.journal.code is capped at 5 chars


def _pos_retail_online_payment_method(env, company):
    """This company's Online Payment method, created with its journal if missing.

    It needs a BANK journal. A payment method without one is what Odoo calls
    "Customer Account": the sale is booked as the customer's debt instead of
    as paid, which is the khata button, not an online payment.

    Returns None while the company has no chart of accounts, because a bank
    journal cannot be created without one. Branches share their parent's
    chart, so the root company is what gets checked.
    """
    Method = env['pos.payment.method'].sudo().with_context(active_test=False)
    method = Method.search([('name', '=', ONLINE_PAYMENT_NAME),
                            ('company_id', '=', company.id)], limit=1)
    if method:
        if not method.active:
            method.active = True
        return method

    Account = env['account.account'].sudo()
    if not Account.search_count([('company_ids', 'in', company.root_id.id)]):
        return None

    Journal = env['account.journal'].sudo()
    journal = Journal.search([('code', '=', ONLINE_PAYMENT_JOURNAL_CODE),
                              ('company_id', '=', company.id)], limit=1)
    if not journal:
        journal = Journal.create({
            'name': ONLINE_PAYMENT_NAME,
            'code': ONLINE_PAYMENT_JOURNAL_CODE,
            'type': 'bank',
            'company_id': company.id,
        })
    # The outstanding account normally comes from the journal onchange, which
    # does not fire on a programmatic create; same lookup as core's
    # _onchange_journal_id (pos_payment_method.py).
    chart = env['account.chart.template'].with_context(allowed_company_ids=company.root_id.ids)
    outstanding = chart.ref('account_journal_payment_debit_account_id', raise_if_not_found=False)
    return Method.create({
        'name': ONLINE_PAYMENT_NAME,
        'journal_id': journal.id,
        'company_id': company.id,
        'outstanding_account_id': (outstanding or company.transfer_account_id).id or False,
    })


def _pos_retail_setup_online_payment(env):
    """Give every register on a fresh install the Online Payment method.

    Databases that already trade are converted by
    scripts/setup_online_payment.py instead, which can wait for a register's
    session to be closed -- Odoo refuses payment-method changes on a register
    while its session is open.
    """
    for config in env['pos.config'].sudo().search([]):
        if config.has_active_session:
            continue
        method = _pos_retail_online_payment_method(env, config.company_id)
        if method and method not in config.payment_method_ids:
            config.write({'payment_method_ids': [(4, method.id)]})


def _pos_retail_post_init(env):
    """Provision tenant data that Odoo has no template for.

    Idempotent on purpose: safe on a fresh tenant install and on re-runs.
    """
    # Store Credit eWallet so refunds can be issued as store credit (native
    # pos_loyalty "eWallet Refund" flow). Uses loyalty's own template so the
    # trigger product, earning rule and reward match one created from Settings.
    LoyaltyProgram = env['loyalty.program']
    if not LoyaltyProgram.search_count([('program_type', '=', 'ewallet')]):
        template = LoyaltyProgram._get_template_values().get('ewallet')
        if template:
            LoyaltyProgram.create({'name': 'Store Credit', 'program_type': 'ewallet', **template})

    _pos_retail_setup_online_payment(env)
    _pos_retail_seed_till_capabilities(env)
    _pos_retail_seed_dashboard_permissions(env)
    _pos_retail_refresh_branch_rules(env)
    _pos_retail_relax_journal_comp_rule(env)
    _pos_retail_fix_company_hierarchy(env)
    _pos_retail_sync_cashier_companies(env)


def _pos_retail_relax_journal_comp_rule(env):
    """Ensure account.journal multi-company rule allows branches to read parent journals and vice-versa."""
    rule = env.ref('account.journal_comp_rule', raise_if_not_found=False)
    if rule:
        desired_domain = "['|', '|', '|', '|', ('company_id', '=', False), ('company_id', 'parent_of', company_ids), ('company_id', 'child_of', company_ids), ('company_id', 'in', company_ids), ('company_id', 'in', user.company_ids.ids)]"
        if rule.domain_force != desired_domain:
            rule.sudo().write({
                'name': 'Journal: visible to branches and parent',
                'domain_force': desired_domain,
            })


def _pos_retail_fix_company_hierarchy(env):
    """Ensure all branch companies have their parent_id set to the root holding company."""
    Company = env['res.company'].sudo()
    root = Company.search([('parent_id', '=', False)], order='id', limit=1)
    if root:
        branches = Company.search([('id', '!=', root.id), ('parent_id', '=', False)])
        if branches:
            branches.write({'parent_id': root.id})

    # Ensure Administrator (user id=2) has access to all companies
    admin_user = env.ref('base.user_admin', raise_if_not_found=False)
    if admin_user:
        all_companies = Company.search([])
        if set(admin_user.company_ids.ids) != set(all_companies.ids):
            admin_user.write({'company_ids': [(6, 0, all_companies.ids)]})


def _pos_retail_sync_cashier_companies(env):
    """Ensure non-super-admin shop staff are restricted to their primary branch."""
    for user in env['res.users'].sudo().search([('share', '=', False)]):
        if not user.has_group('base.group_system') and user.company_id:
            if set(user.company_ids.ids) != {user.company_id.id}:
                user.write({'company_ids': [(6, 0, [user.company_id.id])]})


def _pos_retail_refresh_branch_rules(env):
    """Ensure branch rules in ir.rule have noupdate=False so updates always apply."""
    rules = env['ir.model.data'].search([
        ('module', '=', 'pos_retail'),
        ('model', '=', 'ir.rule'),
    ])
    if rules:
        rules.write({'noupdate': False})


def _pos_retail_seed_dashboard_permissions(env):
    """Ensure all 9 dashboard permissions have category='dashboard' and are attached to Admin role.

    Programmatically forced because noupdate=1 on earlier data imports prevented field updates
    during module upgrade.
    """
    admin_role = env.ref('pos_retail.access_role_admin', raise_if_not_found=False)
    dash_perms = [
        'pos_retail.perm_dash_sales',
        'pos_retail.perm_dash_financials',
        'pos_retail.perm_dash_payments',
        'pos_retail.perm_dash_inventory',
        'pos_retail.perm_dash_stock_movement',
        'pos_retail.perm_dash_product_movement',
        'pos_retail.perm_dash_sales_trend',
        'pos_retail.perm_dash_top_lists',
        'pos_retail.perm_dash_alerts',
    ]
    perm_ids = []
    for xmlid in dash_perms:
        perm = env.ref(xmlid, raise_if_not_found=False)
        if perm:
            if perm.category != 'dashboard':
                perm.write({'category': 'dashboard'})
            if admin_role and perm.id not in admin_role.permission_ids.ids:
                perm_ids.append(perm.id)
            data_rec = env['ir.model.data'].search([
                ('module', '=', 'pos_retail'),
                ('name', '=', xmlid.split('.')[1]),
            ], limit=1)
            if data_rec and data_rec.noupdate:
                data_rec.noupdate = False
    if admin_role and perm_ids:
        admin_role.write({'permission_ids': [(4, pid) for pid in perm_ids]})


def _pos_retail_seed_till_capabilities(env):
    """Point the shipped permissions at the till buttons they unlock.

    Done here rather than in the data file because that file is noupdate: it
    has to be, so a shop's own edits to the catalogue survive every upgrade.
    The cost is that a field added later never reaches a database that already
    has those records, which is exactly this field.

    Only fills a capability that is still EMPTY. A shop that has moved a
    button onto a permission of their own keeps that arrangement; this never
    overrules a decision somebody made on purpose.
    """
    defaults = {
        'pos_retail.perm_khata_adjust': '_can_khata',
        'pos_retail.perm_pos_admin': '_can_admin_panel',
        'pos_retail.perm_products_create': '_can_create_product',
        'pos_retail.perm_products_edit': '_can_edit_product',
        'pos_retail.perm_inventory': '_can_stock_adjust',
        'pos_retail.perm_reporting': '_can_daily_sales',
        # Seeded onto the everyday till permission so no shop loses the
        # refund button by upgrading. Move it to perm_refund to restrict.
        'pos_retail.perm_pos_use': '_can_refund',
    }
    for xmlid, capability in defaults.items():
        permission = env.ref(xmlid, raise_if_not_found=False)
        if permission and not permission.till_capability:
            permission.till_capability = capability
