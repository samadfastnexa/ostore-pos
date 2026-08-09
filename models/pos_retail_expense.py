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

    name = fields.Char(
        required=True,
        help="Short description of what the money was spent on, for example "
             "'Shop rent for March' or 'Diesel for the generator'.",
    )
    category = fields.Selection(
        EXPENSE_CATEGORIES, required=True, default='miscellaneous', tracking=True,
        help="Groups the expense for reporting, so you can see how much goes on "
             "rent, salaries, fuel and so on. Choose Miscellaneous when nothing "
             "else fits.",
    )
    amount = fields.Monetary(
        required=True, currency_field='currency_id', tracking=True,
        help="How much was spent, in the currency below. It must be greater than "
             "zero; money coming back to you belongs on a separate record, not as "
             "a negative amount here.",
    )
    currency_id = fields.Many2one(
        'res.currency', default=lambda self: self.env.company.currency_id, required=True,
        help="Currency the amount above is expressed in. It defaults to your "
             "company currency; change it only if you genuinely paid in a "
             "different one.",
    )
    vendor_id = fields.Many2one(
        'res.partner', string="Vendor",
        help="Who was paid, for example the landlord, the electricity company or "
             "a supplier. Leave it blank for small cash costs where the payee "
             "does not need tracking.",
    )
    date = fields.Date(
        required=True, default=fields.Date.context_today, tracking=True,
        help="The day the money actually left the business. Reports count the "
             "expense under this date, so use the payment date rather than the "
             "day you typed it in.",
    )
    payment_method = fields.Selection(
        PAYMENT_METHODS, required=True, default='cash',
        help="How the money was paid out: cash from the till or safe, a bank "
             "transfer, a cheque, or anything else. This makes it easier to "
             "reconcile your cash and bank balances at the end of the day.",
    )
    notes = fields.Text(
        help="Extra detail worth keeping, such as a bill or receipt number or "
             "what a repair covered. It stays inside this record and is never "
             "printed for a customer.",
    )
    company_id = fields.Many2one(
        'res.company', default=lambda self: self.env.company, required=True,
        help="The company whose books this expense is recorded against. It only "
             "matters if you run more than one company in the system; otherwise "
             "leave it as it is.",
    )
    active = fields.Boolean(
        default=True,
        help="Untick to archive this expense and take it out of the everyday "
             "list. Nothing is deleted; use the Archived filter to find it "
             "again or tick the box to bring it back.",
    )

    @api.constrains('amount')
    def _check_amount_positive(self):
        for expense in self:
            if expense.amount <= 0:
                raise ValidationError(_("Expense amount must be greater than zero."))
