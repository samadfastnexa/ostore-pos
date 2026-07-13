from odoo import _, api, fields, models


class ResPartner(models.Model):
    _inherit = 'res.partner'

    birthday = fields.Date(string="Birthday")
    membership_level_id = fields.Many2one(
        'pos.membership.level', string="Membership Level", index=True,
        ondelete='set null',
    )

    mobile = fields.Char(string="Mobile")
    vendor_contact_person = fields.Char(string="Contact Person")
    supplierinfo_ids = fields.One2many(
        'product.supplierinfo', 'partner_id', string="Products Supplied",
    )
    products_supplied_count = fields.Integer(
        string="# Products Supplied", compute='_compute_products_supplied_count',
    )

    @api.model
    def _load_pos_data_fields(self, config):
        result = super()._load_pos_data_fields(config)
        for fname in ('birthday', 'membership_level_id'):
            if fname not in result:
                result.append(fname)
        return result

    def _compute_products_supplied_count(self):
        counts = dict(self.env['product.supplierinfo']._read_group(
            domain=[('partner_id', 'in', self.ids)],
            groupby=['partner_id'],
            aggregates=['product_tmpl_id:count_distinct'],
        ))
        for partner in self:
            partner.products_supplied_count = counts.get(partner, 0)

    def action_view_supplierinfo(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _("Products Supplied"),
            'res_model': 'product.supplierinfo',
            'view_mode': 'list,form',
            'domain': [('partner_id', '=', self.id)],
            'context': {'default_partner_id': self.id},
        }

    def action_view_outstanding_bills(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _("Outstanding Vendor Bills"),
            'res_model': 'account.move',
            'view_mode': 'list,form',
            'domain': [
                ('partner_id', 'child_of', self.id),
                ('move_type', 'in', ('in_invoice', 'in_refund')),
                ('payment_state', '!=', 'paid'),
            ],
            'context': {'default_move_type': 'in_invoice', 'default_partner_id': self.id},
        }
