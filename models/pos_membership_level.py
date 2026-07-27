from odoo import api, fields, models


class PosMembershipLevel(models.Model):
    _name = 'pos.membership.level'
    # pos.load.mixin: loaded into the POS session so the receipt (and any POS
    # screen) can resolve partner.membership_level_id.name client-side. A
    # handful of rows; negligible payload.
    _inherit = ['pos.load.mixin']
    _description = "POS Customer Membership Level"
    _order = 'sequence, id'

    @api.model
    def _load_pos_data_fields(self, config):
        return ['id', 'name', 'sequence', 'color', 'discount']

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
