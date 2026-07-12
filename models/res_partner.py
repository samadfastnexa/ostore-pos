from odoo import api, fields, models


class ResPartner(models.Model):
    _inherit = 'res.partner'

    birthday = fields.Date(string="Birthday")
    membership_level_id = fields.Many2one(
        'pos.membership.level', string="Membership Level", index=True,
        ondelete='set null',
    )

    @api.model
    def _load_pos_data_fields(self, config):
        result = super()._load_pos_data_fields(config)
        for fname in ('birthday', 'membership_level_id'):
            if fname not in result:
                result.append(fname)
        return result
