from odoo import _, api, fields, models
from odoo.exceptions import UserError

from .res_company import TRADING_COMPANY_DOMAIN


class PosRetailLedgerAdjustment(models.TransientModel):
    """Khata adjustment: change what a customer owes WITHOUT faking history.

    Posted ledger rows are immutable by design (core protects posted journal
    items; that is what makes the ledger trustworthy), so an adjustment is a
    NEW, properly balanced journal entry on the customer's receivable account:
    old debt brought in from a paper khata, an opening balance at migration,
    a waived amount, a correction. The ledger and the "Amount Owed" figure
    update the moment it posts, and the entry itself shows in the ledger with
    the given reason, so the trail stays complete.
    """
    _name = 'pos.retail.ledger.adjustment'
    _description = "Customer Ledger Adjustment"

    partner_id = fields.Many2one(
        'res.partner', string="Customer", required=True,
        default=lambda self: self.env.context.get('default_partner_id'),
        help="The customer whose outstanding balance is being corrected. The "
             "entry is posted against this customer's account, so it changes "
             "their Amount Owed and shows as a new line on their ledger.",
    )
    current_balance = fields.Monetary(
        string="Current Balance", compute='_compute_current_balance', currency_field='currency_id',
    )
    adjustment_mode = fields.Selection(
        [
            ('relative', "Adjust by Amount (+ / −)"),
            ('target', "Set Exact Target Balance"),
        ],
        string="Adjustment Mode", default='relative', required=True,
    )
    target_balance = fields.Monetary(
        string="Desired New Balance", currency_field='currency_id',
        help="Enter the exact new balance you want this customer to have. The system will calculate the adjustment.",
    )
    direction = fields.Selection(
        [
            ('increase', "Customer owes MORE (old debt / opening balance / charge)"),
            ('decrease', "Customer owes LESS (waive / discount / correction)"),
        ],
        required=True, default='increase',
        help="Choose 'owes MORE' to bring in a debt the system does not know "
             "about yet, such as a balance carried over from a paper khata; "
             "choose 'owes LESS' to waive an amount or correct one downwards.",
    )
    amount = fields.Monetary(
        required=True, currency_field='currency_id',
        help="How much to move the balance by, always typed in as a positive "
             "number. The direction above decides whether it is added to or "
             "taken off what the customer owes.",
    )
    currency_id = fields.Many2one(
        'res.currency', default=lambda self: self.env.company.currency_id,
        help="Currency the amount above is measured in. It defaults to your "
             "company currency.",
    )
    date = fields.Date(
        required=True, default=fields.Date.context_today,
        help="The date the accounting entry is filed under. Use the day the debt "
             "really arose or was waived, because the ledger and your accounts "
             "are ordered by this date, not by when you keyed it in.",
    )
    reason = fields.Char(
        required=True,
        help="Shown on the ledger line and on the journal entry, e.g. "
             "'Old khata balance brought forward'.",
    )
    company_id = fields.Many2one(
        'res.company', string="Branch", domain=TRADING_COMPANY_DOMAIN,
        compute='_compute_company_id', store=True, readonly=False,
        help="Branch whose books the entry is posted in. Taken from the "
             "customer, since a customer belongs to one branch.",
    )
    counterpart_account_id = fields.Many2one(
        'account.account', string="Counterpart Account",
        compute='_compute_counterpart_account_id', store=True, readonly=False,
        domain="[('account_type', 'not in', ('asset_receivable', 'liability_payable'))]",
        help="The other side of the entry, filled in for you from the direction "
             "above: equity for a balance brought forward, an expense account "
             "for an amount written off. Change it only if your accountant asks "
             "you to; the customer's balance is the same either way.",
    )
    journal_id = fields.Many2one(
        'account.journal', string="Journal",
        compute='_compute_journal_id', store=True, readonly=False,
        domain="[('type', '=', 'general'), ('company_id', '=', company_id)]",
        help="The book the entry is filed in. Filled in for you; it decides "
             "where your accountant finds the entry and has no effect on what "
             "the customer owes.",
    )

    @api.depends('partner_id')
    def _compute_current_balance(self):
        for wizard in self:
            wizard.current_balance = wizard.partner_id.pos_outstanding_balance or 0.0

    @api.onchange('adjustment_mode', 'target_balance', 'current_balance')
    def _onchange_target_balance(self):
        if self.adjustment_mode == 'target' and self.partner_id:
            diff = (self.target_balance or 0.0) - (self.current_balance or 0.0)
            if diff >= 0:
                self.direction = 'increase'
                self.amount = diff
            else:
                self.direction = 'decrease'
                self.amount = abs(diff)

    @api.depends('partner_id')
    def _compute_company_id(self):
        for wizard in self:
            wizard.company_id = wizard.partner_id.company_id or self.env.company

    @api.depends('direction', 'company_id')
    def _compute_counterpart_account_id(self):
        Account = self.env['account.account']
        for wizard in self:
            company = wizard.company_id or self.env.company
            accounts = Account.with_company(company)
            wanted = 'equity' if wizard.direction == 'increase' else 'expense'
            match = accounts.search([('account_type', '=', wanted)], limit=1)
            if not match:
                match = accounts.search([
                    ('account_type', 'not in', ('asset_receivable', 'liability_payable')),
                ], limit=1)
            wizard.counterpart_account_id = match

    @api.depends('company_id')
    def _compute_journal_id(self):
        Journal = self.env['account.journal'].sudo()
        for wizard in self:
            company = wizard.company_id or self.env.company
            base = [('type', '=', 'general'), ('company_id', '=', company.id)]
            match = (Journal.search(base + [('code', '=', 'MISC')], limit=1)
                     or Journal.search(base + [('name', 'ilike', 'miscellaneous')], limit=1)
                     or Journal.search(base + [('name', 'not ilike', 'point of sale')], limit=1)
                     or Journal.search(base, limit=1))
            wizard.journal_id = match

    def action_confirm(self):
        self.ensure_one()
        if self.adjustment_mode == 'target':
            diff = self.target_balance - self.current_balance
            if abs(diff) < 0.005:
                raise UserError(_("The desired new balance is already identical to the current balance."))
            if diff > 0:
                self.direction = 'increase'
                self.amount = diff
            else:
                self.direction = 'decrease'
                self.amount = abs(diff)

        if self.amount <= 0:
            raise UserError(_("The amount must be positive; use the direction "
                              "field to choose whether the customer owes more or less."))
        receivable = self.partner_id.property_account_receivable_id
        if not receivable:
            raise UserError(_("This customer has no receivable account configured."))
        inc = self.direction == 'increase'
        company = self.company_id or self.env.company
        move = self.env['account.move'].with_company(company).create({
            'move_type': 'entry',
            'company_id': company.id,
            'journal_id': self.journal_id.id,
            'date': self.date,
            'ref': self.reason,
            'line_ids': [
                (0, 0, {
                    'partner_id': self.partner_id.id,
                    'account_id': receivable.id,
                    'name': self.reason,
                    'debit': self.amount if inc else 0.0,
                    'credit': 0.0 if inc else self.amount,
                }),
                (0, 0, {
                    'partner_id': self.partner_id.id,
                    'account_id': self.counterpart_account_id.id,
                    'name': self.reason,
                    'debit': 0.0 if inc else self.amount,
                    'credit': self.amount if inc else 0.0,
                }),
            ],
        })
        move.action_post()

        # If owes less, reconcile against open receivable lines
        if not inc:
            open_lines = self.env['account.move.line'].sudo().search([
                ('partner_id', '=', self.partner_id.id),
                ('account_id', '=', receivable.id),
                ('parent_state', '=', 'posted'),
                ('reconciled', '=', False),
                ('company_id', '=', company.id),
            ], order='date asc, id asc')
            if len(open_lines) >= 2 and any(l.debit > 0 for l in open_lines) and any(l.credit > 0 for l in open_lines):
                try:
                    open_lines.reconcile()
                except Exception:
                    pass

        self.env.flush_all()
        # Straight back to the ledger, where the new row is now visible.
        return self.partner_id.action_view_customer_ledger()


class PosRetailVendorLedgerAdjustment(models.TransientModel):
    """Vendor khata adjustment: change what the shop owes a supplier WITHOUT faking history.

    Creates a new, balanced journal entry on the vendor's payable account:
    old debt brought forward, supplier rebate, return deduction, waiver, correction.
    """
    _name = 'pos.retail.vendor.ledger.adjustment'
    _description = "Vendor Ledger Adjustment"

    partner_id = fields.Many2one(
        'res.partner', string="Vendor", required=True,
        domain="[('supplier_rank', '>', 0)]",
        default=lambda self: self.env.context.get('default_partner_id'),
        help="The supplier whose payable balance is being adjusted.",
    )
    current_balance = fields.Monetary(
        string="Current Payable", compute='_compute_current_balance', currency_field='currency_id',
    )
    adjustment_mode = fields.Selection(
        [
            ('relative', "Adjust by Amount (+ / −)"),
            ('target', "Set Exact Target Payable"),
        ],
        string="Adjustment Mode", default='relative', required=True,
    )
    target_balance = fields.Monetary(
        string="Desired New Payable", currency_field='currency_id',
        help="Enter the exact new payable amount you want this vendor to have.",
    )
    direction = fields.Selection(
        [
            ('decrease', "Shop owes LESS (rebate / discount / waiver / correction)"),
            ('increase', "Shop owes MORE (unbilled invoice / old paper debt)"),
        ],
        required=True, default='decrease',
        help="Choose 'Shop owes LESS' for supplier discounts, waivers, or return credits; "
             "choose 'Shop owes MORE' to bring in unbilled deliveries or opening balances.",
    )
    amount = fields.Monetary(
        required=True, currency_field='currency_id',
        help="How much to adjust the payable by, always typed in as a positive number.",
    )
    currency_id = fields.Many2one(
        'res.currency', default=lambda self: self.env.company.currency_id,
    )
    date = fields.Date(
        required=True, default=fields.Date.context_today,
        help="The accounting date for this adjustment entry.",
    )
    reason = fields.Char(
        required=True,
        help="Shown on the ledger line and journal entry, e.g. \"Vendor rebate / Volume discount\".",
    )
    company_id = fields.Many2one(
        'res.company', string="Branch", domain=TRADING_COMPANY_DOMAIN,
        compute='_compute_company_id', store=True, readonly=False,
    )
    counterpart_account_id = fields.Many2one(
        'account.account', string="Counterpart Account",
        compute='_compute_counterpart_account_id', store=True, readonly=False,
        domain="[('account_type', 'not in', ('asset_receivable', 'liability_payable'))]",
    )
    journal_id = fields.Many2one(
        'account.journal', string="Journal",
        compute='_compute_journal_id', store=True, readonly=False,
        domain="[('type', '=', 'general'), ('company_id', '=', company_id)]",
    )

    @api.depends('partner_id')
    def _compute_current_balance(self):
        for wizard in self:
            if not wizard.partner_id:
                wizard.current_balance = 0.0
                continue
            pay_grouped = self.env['account.move.line'].sudo()._read_group(
                domain=[
                    ('partner_id', '=', wizard.partner_id.id),
                    ('account_id.account_type', '=', 'liability_payable'),
                    ('parent_state', '=', 'posted'),
                ],
                aggregates=('debit:sum', 'credit:sum'),
            )
            prev_debit, prev_credit = pay_grouped[0] if pay_grouped else (0.0, 0.0)
            wizard.current_balance = round((prev_credit or 0.0) - (prev_debit or 0.0), 2)

    @api.onchange('adjustment_mode', 'target_balance', 'current_balance')
    def _onchange_target_balance(self):
        if self.adjustment_mode == 'target' and self.partner_id:
            diff = (self.target_balance or 0.0) - (self.current_balance or 0.0)
            if diff >= 0:
                self.direction = 'increase'
                self.amount = diff
            else:
                self.direction = 'decrease'
                self.amount = abs(diff)

    @api.depends('partner_id')
    def _compute_company_id(self):
        for wizard in self:
            wizard.company_id = wizard.partner_id.company_id or self.env.company

    @api.depends('direction', 'company_id')
    def _compute_counterpart_account_id(self):
        Account = self.env['account.account']
        for wizard in self:
            company = wizard.company_id or self.env.company
            accounts = Account.with_company(company)
            wanted = 'income' if wizard.direction == 'decrease' else 'expense'
            match = accounts.search([('account_type', '=', wanted)], limit=1)
            if not match:
                match = accounts.search([('account_type', '=', 'equity')], limit=1)
            if not match:
                match = accounts.search([
                    ('account_type', 'not in', ('asset_receivable', 'liability_payable')),
                ], limit=1)
            wizard.counterpart_account_id = match

    @api.depends('company_id')
    def _compute_journal_id(self):
        Journal = self.env['account.journal'].sudo()
        for wizard in self:
            company = wizard.company_id or self.env.company
            base = [('type', '=', 'general'), ('company_id', '=', company.id)]
            match = (Journal.search(base + [('code', '=', 'MISC')], limit=1)
                     or Journal.search(base + [('name', 'ilike', 'miscellaneous')], limit=1)
                     or Journal.search(base + [('name', 'not ilike', 'point of sale')], limit=1)
                     or Journal.search(base, limit=1))
            wizard.journal_id = match

    def action_confirm(self):
        self.ensure_one()
        if self.adjustment_mode == 'target':
            diff = self.target_balance - self.current_balance
            if abs(diff) < 0.005:
                raise UserError(_("The desired new payable balance is already identical to the current payable."))
            if diff > 0:
                self.direction = 'increase'
                self.amount = diff
            else:
                self.direction = 'decrease'
                self.amount = abs(diff)

        if self.amount <= 0:
            raise UserError(_("The amount must be positive; choose whether the shop owes more or less."))
        payable = self.partner_id.property_account_payable_id
        if not payable:
            raise UserError(_("This vendor has no payable account configured."))
        inc = self.direction == 'increase'
        company = self.company_id or self.env.company
        move = self.env['account.move'].with_company(company).create({
            'move_type': 'entry',
            'company_id': company.id,
            'journal_id': self.journal_id.id,
            'date': self.date,
            'ref': self.reason,
            'line_ids': [
                (0, 0, {
                    'partner_id': self.partner_id.id,
                    'account_id': payable.id,
                    'name': self.reason,
                    'debit': 0.0 if inc else self.amount,
                    'credit': self.amount if inc else 0.0,
                }),
                (0, 0, {
                    'partner_id': self.partner_id.id,
                    'account_id': self.counterpart_account_id.id,
                    'name': self.reason,
                    'debit': self.amount if inc else 0.0,
                    'credit': 0.0 if inc else self.amount,
                }),
            ],
        })
        move.action_post()

        # If owes less, reconcile against open bills
        if not inc:
            open_lines = self.env['account.move.line'].sudo().search([
                ('partner_id', '=', self.partner_id.id),
                ('account_id', '=', payable.id),
                ('parent_state', '=', 'posted'),
                ('reconciled', '=', False),
                ('company_id', '=', company.id),
            ], order='date asc, id asc')
            if len(open_lines) >= 2 and any(l.debit > 0 for l in open_lines) and any(l.credit > 0 for l in open_lines):
                try:
                    open_lines.reconcile()
                except Exception:
                    pass

        self.env.flush_all()
        # Straight back to the vendor ledger
        return {
            'type': 'ir.actions.act_window',
            'name': _("Vendor Ledger"),
            'res_model': 'pos.retail.vendor.ledger.line',
            'view_mode': 'list,form',
            'domain': [('partner_id', '=', self.partner_id.id)],
            'context': {'default_partner_id': self.partner_id.id},
        }
