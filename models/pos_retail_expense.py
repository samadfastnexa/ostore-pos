from odoo import _, api, fields, models
from odoo.exceptions import ValidationError

EXPENSE_CATEGORIES = [
    ('rent', 'Rent'),
    ('electricity', 'Electricity'),
    ('salaries', 'Salaries'),
    ('internet', 'Internet'),
    ('fuel', 'Fuel'),
    ('maintenance', 'Maintenance'),
    ('marketing', 'Marketing'),
    ('miscellaneous', 'Miscellaneous'),
]

PAYMENT_METHODS = [
    ('cash', 'Cash'),
    ('bank', 'Bank'),
    ('cheque', 'Cheque'),
    ('other', 'Other'),
]


class PosRetailExpense(models.Model):
    _name = 'pos.retail.expense'
    _description = "POS Retail Business Expense"
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _rec_name = 'name'
    _order = 'date desc, id desc'

    name = fields.Char(required=True)
    category = fields.Selection(EXPENSE_CATEGORIES, required=True, default='miscellaneous', tracking=True)
    amount = fields.Monetary(required=True, currency_field='currency_id', tracking=True)
    currency_id = fields.Many2one(
        'res.currency', default=lambda self: self.env.company.currency_id, required=True
    )
    vendor_id = fields.Many2one('res.partner', string="Vendor")
    date = fields.Date(required=True, default=fields.Date.context_today, tracking=True)
    payment_method = fields.Selection(PAYMENT_METHODS, required=True, default='cash')
    notes = fields.Text()
    company_id = fields.Many2one('res.company', default=lambda self: self.env.company, required=True)
    active = fields.Boolean(default=True)

    @api.constrains('amount')
    def _check_amount_positive(self):
        for expense in self:
            if expense.amount <= 0:
                raise ValidationError(_("Expense amount must be greater than zero."))
