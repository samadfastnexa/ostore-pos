from odoo import api, models


class PosSession(models.Model):
    _inherit = 'pos.session'

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            vals['update_stock_at_closing'] = False
        return super().create(vals_list)

    def load_data(self, models_to_load):
        # POS always operates strictly within its session's company context
        if self.company_id:
            self = self.with_company(self.company_id)
        response = super(PosSession, self).load_data(models_to_load)

        # Guarantee the session and register records are present in the response payload
        # so frontend pos_store.js can resolve this.session and this.config even under
        # multi-company cookie mismatches or strict record rules.
        if self and 'pos.session' in response and self.id not in [r.get('id') for r in response['pos.session']]:
            session_data = self.sudo()._load_pos_data_read(self, self.config_id)
            response['pos.session'].extend(session_data)
        if self.config_id and 'pos.config' in response and self.config_id.id not in [r.get('id') for r in response['pos.config']]:
            config_data = self.config_id.sudo()._load_pos_data_read(self.config_id, self.config_id)
            response['pos.config'].extend(config_data)
        return response

    def load_data_params(self):
        if self.company_id:
            self = self.with_company(self.company_id)
        return super(PosSession, self).load_data_params()

    def filter_local_data(self, local_records):
        if self.company_id:
            self = self.with_company(self.company_id)
        return super(PosSession, self).filter_local_data(local_records)

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
