from odoo import _, api, fields, models
from odoo.exceptions import ValidationError

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

    pos_retail_discount_enabled = fields.Boolean(
        string="Enable Order Discounts", default=True,
        help="Allow cashiers to apply a discount to the whole order from the "
             "Payment Screen, on top of any per-product discounts.",
    )
    pos_retail_max_roundoff_amount = fields.Monetary(
        string="Maximum Round-Off Amount", default=5.0,
        currency_field='currency_id',
        help="The configured cash-rounding increment cannot exceed this amount.",
    )
    pos_retail_max_fixed_discount = fields.Monetary(
        string="Maximum Cashier Discount (Fixed)", default=100.0,
        currency_field='currency_id',
        help="Fallback fixed-discount limit used when an employee has no "
             "Discount Role assigned.",
    )
    pos_retail_max_percentage_discount = fields.Float(
        string="Maximum Cashier Discount (%)", default=5.0,
        help="Fallback percentage-discount limit used when an employee has no "
             "Discount Role assigned.",
    )
    pos_retail_require_discount_reason = fields.Boolean(
        string="Require Discount Reason", default=True,
        help="Cashiers must select or enter a reason whenever an order "
             "discount is applied.",
    )
    pos_retail_require_manager_approval = fields.Boolean(
        string="Require Manager Approval", default=True,
        help="If enabled, a discount beyond the cashier's limit can proceed "
             "after a manager authenticates via PIN. If disabled, over-limit "
             "discounts are blocked outright with no approval path.",
    )
    pos_retail_allow_manager_override = fields.Boolean(
        string="Allow Manager Override", default=True,
        help="If enabled, a manager's PIN approval allows any discount "
             "amount. If disabled, the approving manager's own Discount Role "
             "limit still applies as a ceiling.",
    )
    pos_retail_receipt_show_discount_details = fields.Boolean(
        string="Show Discount Details on Receipt", default=True,
        help="Print the manager name (if approval was required) and the "
             "discount reason on the receipt.",
    )
    # --- Returns & Refunds (#12) ---
    pos_retail_require_return_reason = fields.Boolean(
        string="Require Return Reason", default=True,
        help="Cashiers must pick a return reason whenever a refund is processed.",
    )
    pos_retail_allow_no_receipt_return = fields.Boolean(
        string="Allow Returns Without Receipt", default=True,
        help="Show a 'Return (No Receipt)' action in the POS so a product can be "
             "refunded without looking up the original order.",
    )
    pos_retail_return_requires_manager = fields.Boolean(
        string="Return Needs Manager Approval", default=True,
        help="Require a manager PIN for a return without a receipt.",
    )

    @api.constrains('cash_rounding', 'rounding_method', 'pos_retail_max_roundoff_amount')
    def _check_max_roundoff_amount(self):
        for config in self:
            if config.cash_rounding and config.rounding_method:
                if config.rounding_method.rounding > config.pos_retail_max_roundoff_amount:
                    raise ValidationError(_(
                        "The cash rounding increment (%(rounding).2f) exceeds the "
                        "configured Maximum Round-Off Amount (%(max).2f).",
                        rounding=config.rounding_method.rounding,
                        max=config.pos_retail_max_roundoff_amount,
                    ))


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    pos_return_policy = fields.Text(
        related='pos_config_id.return_policy',
        readonly=False,
        string="Return Policy",
    )
    pos_retail_discount_enabled = fields.Boolean(
        related='pos_config_id.pos_retail_discount_enabled',
        readonly=False,
        string="Enable Order Discounts",
    )
    pos_retail_max_roundoff_amount = fields.Monetary(
        related='pos_config_id.pos_retail_max_roundoff_amount',
        readonly=False,
        string="Maximum Round-Off Amount",
    )
    pos_retail_max_fixed_discount = fields.Monetary(
        related='pos_config_id.pos_retail_max_fixed_discount',
        readonly=False,
        string="Maximum Cashier Discount (Fixed)",
    )
    pos_retail_max_percentage_discount = fields.Float(
        related='pos_config_id.pos_retail_max_percentage_discount',
        readonly=False,
        string="Maximum Cashier Discount (%)",
    )
    pos_retail_require_discount_reason = fields.Boolean(
        related='pos_config_id.pos_retail_require_discount_reason',
        readonly=False,
        string="Require Discount Reason",
    )
    pos_retail_require_manager_approval = fields.Boolean(
        related='pos_config_id.pos_retail_require_manager_approval',
        readonly=False,
        string="Require Manager Approval",
    )
    pos_retail_require_return_reason = fields.Boolean(
        related='pos_config_id.pos_retail_require_return_reason',
        readonly=False,
        string="Require Return Reason",
    )
    pos_retail_allow_no_receipt_return = fields.Boolean(
        related='pos_config_id.pos_retail_allow_no_receipt_return',
        readonly=False,
        string="Allow Returns Without Receipt",
    )
    pos_retail_return_requires_manager = fields.Boolean(
        related='pos_config_id.pos_retail_return_requires_manager',
        readonly=False,
        string="Return Needs Manager Approval",
    )
    pos_retail_allow_manager_override = fields.Boolean(
        related='pos_config_id.pos_retail_allow_manager_override',
        readonly=False,
        string="Allow Manager Override",
    )
    pos_retail_receipt_show_discount_details = fields.Boolean(
        related='pos_config_id.pos_retail_receipt_show_discount_details',
        readonly=False,
        string="Show Discount Details on Receipt",
    )
