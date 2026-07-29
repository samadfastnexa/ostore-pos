from odoo import _, api, fields, models
from odoo.exceptions import ValidationError

DEFAULT_RETURN_POLICY = (
    "Returns accepted within 7 days with the original receipt.\n"
    "Perishable, promotional and clearance items are non-returnable.\n"
    "Refunds are issued to the original payment method."
)

# Shop colour choices for the POS look. The value is used verbatim as a data
# attribute on the POS root element; the matching hex lives in pos_theme.scss
# so there is a single source of truth for the palette.
POS_RETAIL_THEME_COLORS = [
    ('purple', 'Purple'),
    ('blue', 'Blue'),
    ('green', 'Green'),
    ('teal', 'Teal'),
    ('orange', 'Orange'),
    ('pink', 'Pink'),
]


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
    # --- Flexible pricing ---
    pos_retail_price_range_enabled = fields.Boolean(
        string="Allow Price Within Range", default=True,
        help="When a product has a selling range (Minimum Selling Price and/or "
             "MRP), ask the cashier to confirm or adjust the price as it is added. "
             "Products without a range are always added instantly at their "
             "standard price, so scanning stays fast.",
    )
    pos_retail_price_override_requires_reason = fields.Boolean(
        string="Require Reason for Price Override", default=True,
        help="Ask for a reason whenever a manager approves a price outside the "
             "allowed range. The reason is stored on the order line for auditing.",
    )
    # --- Appearance ---
    pos_retail_theme_color = fields.Selection(
        POS_RETAIL_THEME_COLORS, string="Shop Colour", default='purple', required=True,
        help="Colours the POS top bar, the selected category and other highlights. "
             "Pay stays green, discounts orange, returns red and customer blue so "
             "cashiers always recognise those actions whatever colour is chosen.",
    )
    # --- Receipt Studio ---
    # Layout, paper width and content of the printed receipt. Native fields
    # already cover: logo (company logo), header/footer messages
    # (receipt_header/receipt_footer), the company address/VAT/contact block,
    # cashier, receipt number, tax detail, auto-print. These add what native
    # has no concept of.
    pos_retail_receipt_style = fields.Selection(
        [('standard', "Standard"), ('modern', "Modern"), ('minimal', "Minimal")],
        string="Receipt Template Style", default='standard', required=True,
        help="Standard: the classic layout. Modern: bolder headings and framed "
             "totals. Minimal: hides the logo and per-line detail for the "
             "shortest possible ticket.",
    )
    pos_retail_receipt_width = fields.Selection(
        [('80', "80 mm (Standard Thermal)"), ('58', "58 mm (Compact Thermal)")],
        string="Receipt Paper Width", default='80', required=True,
        help="Match your thermal printer's paper roll. Affects both printer "
             "output and the browser print preview.",
    )
    pos_retail_receipt_font = fields.Selection(
        [('small', "Small"), ('normal', "Normal"), ('large', "Large")],
        string="Receipt Font Size", default='normal', required=True,
        help="How big the printed text is on the ticket. Small fits more lines "
             "per receipt and saves paper; Large is easier for customers to "
             "read but makes every receipt longer.",
    )
    pos_retail_receipt_show_sku = fields.Boolean(
        string="Show SKU on Receipt Lines", default=True,
        help="Print each product's internal reference under its line.",
    )
    pos_retail_receipt_show_qr = fields.Boolean(
        string="Show Receipt QR Code", default=True,
        help="Print a QR code of the receipt reference for quick lookup.",
    )
    pos_retail_receipt_show_ref_barcode = fields.Boolean(
        string="Show Reference Barcode", default=False,
        help="Print the receipt reference as a scannable Code128 barcode in "
             "the footer. Needs a network connection at print time.",
    )
    pos_retail_receipt_thankyou = fields.Char(
        string="Thank-You Message", default="Thank you for shopping with us!",
        help="Printed prominently above the receipt footer. Leave empty to skip.",
    )
    pos_retail_receipt_social = fields.Char(
        string="Website & Social Line",
        help="One line for your website and social handles, printed under the "
             "store name in the footer. Example: www.mystore.pk | fb.com/mystore",
    )
    pos_retail_receipt_terms = fields.Text(
        string="Terms & Conditions",
        help="Printed on PDF receipts (A4). Kept off the thermal ticket to "
             "save paper; the Return Policy block covers the essentials there.",
    )
    # --- Quotations (#11) ---
    pos_retail_allow_quotation = fields.Boolean(
        string="Allow Quotations", default=True,
        help="Show a 'Save as Quotation' action in the POS so a cart can be saved "
             "as a Sales quotation (sale.order) instead of being paid at the till. "
             "The quotation can later be settled back into the POS for payment.",
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
    pos_retail_quote_show_images = fields.Boolean(
        related='company_id.pos_retail_quote_show_images',
        readonly=False,
        string="Show Product Images on Quotations",
    )
    pos_retail_quote_show_qr = fields.Boolean(
        related='company_id.pos_retail_quote_show_qr',
        readonly=False,
        string="Show QR Code on Quotations",
    )
    pos_retail_allow_quotation = fields.Boolean(
        related='pos_config_id.pos_retail_allow_quotation',
        readonly=False,
        string="Allow Quotations",
    )
    pos_retail_theme_color = fields.Selection(
        related='pos_config_id.pos_retail_theme_color',
        readonly=False,
        string="Shop Colour",
    )
    pos_retail_price_range_enabled = fields.Boolean(
        related='pos_config_id.pos_retail_price_range_enabled',
        readonly=False,
        string="Allow Price Within Range",
    )
    pos_retail_price_override_requires_reason = fields.Boolean(
        related='pos_config_id.pos_retail_price_override_requires_reason',
        readonly=False,
        string="Require Reason for Price Override",
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
    pos_retail_receipt_style = fields.Selection(
        related='pos_config_id.pos_retail_receipt_style',
        readonly=False,
        string="Receipt Template Style",
    )
    pos_retail_receipt_width = fields.Selection(
        related='pos_config_id.pos_retail_receipt_width',
        readonly=False,
        string="Receipt Paper Width",
    )
    pos_retail_receipt_font = fields.Selection(
        related='pos_config_id.pos_retail_receipt_font',
        readonly=False,
        string="Receipt Font Size",
    )
    pos_retail_receipt_show_sku = fields.Boolean(
        related='pos_config_id.pos_retail_receipt_show_sku',
        readonly=False,
        string="Show SKU on Receipt Lines",
    )
    pos_retail_receipt_show_qr = fields.Boolean(
        related='pos_config_id.pos_retail_receipt_show_qr',
        readonly=False,
        string="Show Receipt QR Code",
    )
    pos_retail_receipt_show_ref_barcode = fields.Boolean(
        related='pos_config_id.pos_retail_receipt_show_ref_barcode',
        readonly=False,
        string="Show Reference Barcode",
    )
    pos_retail_receipt_thankyou = fields.Char(
        related='pos_config_id.pos_retail_receipt_thankyou',
        readonly=False,
        string="Thank-You Message",
    )
    pos_retail_receipt_social = fields.Char(
        related='pos_config_id.pos_retail_receipt_social',
        readonly=False,
        string="Website & Social Line",
    )
    pos_retail_receipt_terms = fields.Text(
        related='pos_config_id.pos_retail_receipt_terms',
        readonly=False,
        string="Terms & Conditions",
    )
