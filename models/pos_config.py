from odoo import fields, models

DEFAULT_RETURN_POLICY = (
    "Returns accepted within 7 days with the original receipt.\n"
    "Perishable, promotional and clearance items are non-returnable.\n"
    "Refunds are issued to the original payment method."
)


class PosConfig(models.Model):
    _inherit = 'pos.config'

    return_policy = fields.Text(
        string="Return Policy",
        default=DEFAULT_RETURN_POLICY,
        help="Printed as a dedicated block on the POS receipt, above the footer.",
    )


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    pos_return_policy = fields.Text(
        related='pos_config_id.return_policy',
        readonly=False,
        string="Return Policy",
    )
