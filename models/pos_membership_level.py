from odoo import fields, models


class PosMembershipLevel(models.Model):
    _name = 'pos.membership.level'
    _description = "POS Customer Membership Level"
    _order = 'sequence, id'

    name = fields.Char(string="Membership Level", required=True, translate=True)
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)
    color = fields.Integer(string="Color Index")
    discount = fields.Float(
        string="Default Discount (%)",
        help="Indicative discount for this tier. The actual in-POS discount is "
             "applied through a Loyalty/Promotion program targeting this level.",
    )
    description = fields.Text()

    _name_uniq = models.Constraint(
        'unique(name)',
        "A membership level with this name already exists.",
    )
