from odoo import models


class PosSession(models.Model):
    _inherit = 'pos.session'

    def _load_pos_data_models(self, config):
        data = super()._load_pos_data_models(config)
        data += ['pos.retail.discount.role', 'pos.retail.discount.reason', 'pos.retail.return.reason',
                 'pos.retail.price.reason', 'pos.membership.level']
        return data
