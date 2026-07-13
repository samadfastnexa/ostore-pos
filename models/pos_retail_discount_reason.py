from odoo import api, fields, models


class PosRetailDiscountReason(models.Model):
    _name = 'pos.retail.discount.reason'
    _inherit = ['pos.load.mixin']
    _description = "POS Order Discount Reason"
    _order = 'sequence, id'

    name = fields.Char(required=True, translate=True)
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)

    _name_uniq = models.Constraint(
        'unique(name)',
        "A discount reason with this name already exists.",
    )

    @api.model
    def _load_pos_data_domain(self, data, config):
        return []

    @api.model
    def _load_pos_data_fields(self, config):
        return ['id', 'name', 'sequence']
