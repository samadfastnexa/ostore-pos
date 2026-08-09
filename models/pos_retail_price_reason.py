from odoo import api, fields, models


class PosRetailPriceReason(models.Model):
    _name = 'pos.retail.price.reason'
    _inherit = ['pos.load.mixin']
    _description = "POS Price Adjustment Reason"
    _order = 'sequence, id'

    name = fields.Char(
        required=True, translate=True,
        help="The wording the cashier picks when changing an item's price at the "
             "till, for example 'Matched a competitor' or 'Manager approved'. It "
             "is saved on the order line so you can review price changes later.",
    )
    sequence = fields.Integer(
        default=10,
        help="Controls the order the reasons are listed at the till and in "
             "lists; the lowest number comes first. Give your most common "
             "reasons the smallest numbers so cashiers find them straight away.",
    )
    active = fields.Boolean(
        default=True,
        help="Untick to take this reason out of the till list from now on. Past "
             "orders that already used it keep their reason, so your old price "
             "change reports stay correct.",
    )

    _name_uniq = models.Constraint(
        'unique(name)',
        "A price reason with this name already exists.",
    )

    @api.model
    def _load_pos_data_domain(self, data, config):
        return []

    @api.model
    def _load_pos_data_fields(self, config):
        return ['id', 'name', 'sequence']
