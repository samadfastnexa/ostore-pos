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

    name = fields.Char(
        string="Membership Level", required=True, translate=True,
        help="Name of the customer tier as your staff will see it on the "
             "customer record and on the receipt, for example Silver, Gold or "
             "Wholesale.",
    )
    sequence = fields.Integer(
        default=10,
        help="Controls the order the tiers appear in lists; the lowest number "
             "comes first. Number them from your entry level upwards so the "
             "list reads in the order customers climb it.",
    )
    active = fields.Boolean(
        default=True,
        help="Untick to retire this tier so it can no longer be given to anyone "
             "new. Customers already on it keep it until you move them to "
             "another level.",
    )
    color = fields.Integer(
        string="Color Index",
        help="Colour used for this tier on cards and tags so staff can spot it "
             "quickly. It is purely visual and changes nothing about prices or "
             "discounts.",
    )
    discount = fields.Float(
        string="Default Discount (%)",
        help="Indicative discount for this tier. The actual in-POS discount is "
             "applied through a Loyalty/Promotion program targeting this level.",
    )
    description = fields.Text(
        help="Your own notes on what this tier is for and how a customer earns "
             "it, such as a yearly spend. It is for staff reference only and is "
             "not shown to the customer.",
    )

    _name_uniq = models.Constraint(
        'unique(name)',
        "A membership level with this name already exists.",
    )
