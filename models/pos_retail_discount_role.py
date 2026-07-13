from odoo import api, fields, models


class PosRetailDiscountRole(models.Model):
    _name = 'pos.retail.discount.role'
    _inherit = ['pos.load.mixin']
    _description = "POS Discount Role (cashier discount limits)"
    _order = 'sequence, id'

    name = fields.Char(required=True, translate=True)
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)
    max_fixed_discount = fields.Monetary(
        string="Maximum Fixed Discount",
        currency_field='currency_id',
        help="Highest fixed-amount order discount an employee with this role "
             "may apply without manager approval.",
    )
    max_percentage_discount = fields.Float(
        string="Maximum Percentage Discount",
        help="Highest percentage order discount an employee with this role "
             "may apply without manager approval.",
    )
    is_unlimited = fields.Boolean(
        string="Unlimited Discount",
        help="Employees with this role can apply any discount amount without "
             "manager approval. The limit fields above are ignored.",
    )
    can_approve = fields.Boolean(
        string="Can Approve Discounts",
        help="Employees with this role can authenticate (via PIN) to approve "
             "another cashier's over-limit discount.",
    )
    currency_id = fields.Many2one(
        'res.currency', default=lambda self: self.env.company.currency_id, required=True,
    )

    _name_uniq = models.Constraint(
        'unique(name)',
        "A discount role with this name already exists.",
    )

    @api.model
    def _load_pos_data_domain(self, data, config):
        return []

    @api.model
    def _load_pos_data_fields(self, config):
        return [
            'id', 'name', 'max_fixed_discount', 'max_percentage_discount',
            'is_unlimited', 'can_approve', 'sequence',
        ]
