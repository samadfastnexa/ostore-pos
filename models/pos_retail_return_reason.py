from odoo import api, fields, models


class PosRetailReturnReason(models.Model):
    _name = 'pos.retail.return.reason'
    _inherit = ['pos.load.mixin']
    _description = "POS Return Reason"
    _order = 'sequence, id'

    name = fields.Char(
        required=True, translate=True,
        help="The wording the cashier picks when taking goods back, for example "
             "'Faulty item', 'Wrong size' or 'Changed mind'. It is saved on the "
             "refund, so you can see why stock is coming back to you.",
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
             "refunds that already used it keep their reason, so your old "
             "returns reports stay correct.",
    )

    _name_uniq = models.Constraint(
        'unique(name)',
        "A return reason with this name already exists.",
    )

    @api.model
    def _load_pos_data_domain(self, data, config):
        return []

    @api.model
    def _load_pos_data_fields(self, config):
        return ['id', 'name', 'sequence']
