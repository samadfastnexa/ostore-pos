from odoo import models


class PosSession(models.Model):
    _inherit = 'pos.session'

    def _load_pos_data_models(self, config):
        data = super()._load_pos_data_models(config)
        data += ['pos.retail.discount.role', 'pos.retail.discount.reason', 'pos.retail.return.reason',
                 'pos.retail.price.reason', 'pos.membership.level',
                 # Required, not optional: product_product._load_pos_data_fields
                 # ships brand_id, and a many2one whose comodel is missing from
                 # this list reaches the client as a dangling relation.
                 'product.brand']
        return data
