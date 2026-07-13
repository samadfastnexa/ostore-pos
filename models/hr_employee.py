from odoo import api, fields, models


class HrEmployee(models.Model):
    _inherit = 'hr.employee'

    pos_discount_role_id = fields.Many2one(
        'pos.retail.discount.role',
        string="POS Discount Role",
        default=lambda self: self.env.ref(
            'pos_retail.discount_role_cashier', raise_if_not_found=False
        ),
        help="Controls how much order-level discount this employee can apply "
             "in the POS without manager approval.",
    )

    @api.model
    def _load_pos_data_fields(self, config):
        result = super()._load_pos_data_fields(config)
        if 'pos_discount_role_id' not in result:
            result.append('pos_discount_role_id')
        return result
