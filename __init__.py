import base64

from odoo.tools import file_open

from . import models

# name, journal code (account.journal.code is capped at 5 chars), icon file.
# Codes match the journals already provisioned in existing databases (JAZZ /
# EASY) so a re-run reuses them instead of creating near-duplicates.
POS_RETAIL_WALLETS = [
    ('JazzCash', 'JAZZ', 'payment_jazzcash.png'),
    ('EasyPaisa', 'EASY', 'payment_easypaisa.png'),
]


def _pos_retail_wallet_icon(filename):
    try:
        with file_open('pos_retail/static/img/%s' % filename, 'rb') as fh:
            return base64.b64encode(fh.read())
    except (IOError, OSError):
        return False


def _pos_retail_setup_wallet_methods(env):
    """Create the Pakistani mobile-wallet payment methods (JazzCash, EasyPaisa)
    for every company that has a chart of accounts, and attach them to that
    company's POS registers.

    Manual (non-terminal) methods: the customer pays in their wallet app, the
    cashier confirms. Each wallet gets its own bank journal so settlements
    reconcile per provider. Idempotent -- existing journals/methods are reused,
    only missing pieces (e.g. the icon) are filled in.
    """
    Journal = env['account.journal']
    Method = env['pos.payment.method']
    ChartTemplate = env['account.chart.template']

    for company in env['res.company'].search([]):
        # No chart of accounts (e.g. a bare branch company): journal creation
        # could not build its default account -- skip until accounting is set up.
        if not env['account.account'].sudo().search_count([('company_ids', 'in', company.id)]):
            continue

        for name, code, icon_file in POS_RETAIL_WALLETS:
            method = Method.search([('name', '=', name), ('company_id', '=', company.id)], limit=1)
            if not method:
                journal = Journal.search([('code', '=', code), ('company_id', '=', company.id)], limit=1)
                if not journal:
                    journal = Journal.create({
                        'name': name,
                        'code': code,
                        'type': 'bank',
                        'company_id': company.id,
                    })
                # Mirror core's default-Card-method pattern (pos_config.py):
                # the outstanding account normally comes from the journal
                # onchange, which does not fire on programmatic create.
                outstanding = ChartTemplate.with_company(company).ref(
                    'account_journal_payment_debit_account_id', raise_if_not_found=False)
                method = Method.create({
                    'name': name,
                    'journal_id': journal.id,
                    'company_id': company.id,
                    'outstanding_account_id': outstanding.id if outstanding else False,
                    'image': _pos_retail_wallet_icon(icon_file),
                })
            elif not method.image:
                method.image = _pos_retail_wallet_icon(icon_file)

            configs = env['pos.config'].search([
                ('company_id', '=', company.id), ('payment_method_ids', 'not in', method.id),
            ])
            if configs:
                configs.write({'payment_method_ids': [(4, method.id)]})


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

    _pos_retail_setup_wallet_methods(env)
