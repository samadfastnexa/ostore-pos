from odoo import api, models


class PosSession(models.Model):
    _inherit = 'pos.session'

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            vals['update_stock_at_closing'] = False
        return super().create(vals_list)

    @api.model
    def _load_pos_data_read(self, records, config):
        read_records = super()._load_pos_data_read(records, config)
        for rec in read_records:
            rec['update_stock_at_closing'] = False
        return read_records

    def _load_pos_data_models(self, config):
        data = super()._load_pos_data_models(config)
        data += ['pos.retail.discount.role', 'pos.retail.discount.reason', 'pos.retail.return.reason',
                 'pos.retail.price.reason', 'pos.membership.level',
                 # Required, not optional: product_product._load_pos_data_fields
                 # ships brand_id, and a many2one whose comodel is missing from
                 # this list reaches the client as a dangling relation.
                 'product.brand',
                 'pos.retail.brand.campaign',
                 'pos.retail.thermal.label.preset']
        return data
