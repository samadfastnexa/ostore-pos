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
             "Maximum Retail Price), ask the cashier to confirm or adjust the "
             "price as it is added. "
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
        [('standard', "Standard"), ('modern', "Modern"), ('minimal', "Minimal"),
         ('invoice', "Invoice (columned)")],
        string="Receipt Template Style", default='standard', required=True,
        help="Standard: the classic layout. Modern: bolder headings and framed "
             "totals. Minimal: hides the logo and per-line detail for the "
             "shortest possible ticket. Invoice: the columned trade layout a "
             "hardware counter prints -- ITEM / QTY / PRICE / DISC / TOTAL in "
             "aligned columns, then Total, Total Discount, Previous Balance and "
             "TOTAL AMOUNT. Best where sales run to many discounted lines or "
             "the customer keeps a khata.",
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
        string="Show Product Code (SKU) on Receipt Lines", default=True,
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
        # NOT "Terms & Conditions": account already owns that label via
        # invoice_terms on res.config.settings, and a duplicate label warns at
        # install and makes the two indistinguishable in field lists.
        string="Receipt Terms & Conditions",
        help="Printed on PDF receipts (A4). Kept off the thermal ticket to "
             "save paper; the Return Policy block covers the essentials there.",
    )
    pos_retail_roundoff_step = fields.Float(
        string="Round-Off Step", default=5.0,
        help="The whole figure a cashier may round a cash bill to, for example "
             "5 or 10. The payment screen offers the two nearest figures and the "
             "cashier picks one, or neither -- it is never applied automatically, "
             "because whether a customer will hand over 240 for a 238 bill "
             "depends on the customer. Set 0 to hide the option entirely.",
    )

    # --- Customers ---
    pos_retail_default_partner_id = fields.Many2one(
        'res.partner', string="Default Customer",
        help="Pre-selected on every new POS order (e.g. a generic 'Walk-in "
             "Customer'). The cashier can still pick a real customer at any "
             "time; leave empty to start orders with no customer, as standard "
             "Odoo does.",
    )
    # --- Quotations (#11) ---
    pos_retail_allow_quotation = fields.Boolean(
        string="Allow Quotations", default=True,
        help="Show a 'Save as Quotation' action in the POS so a cart can be saved "
             "as a Sales quotation (sale.order) instead of being paid at the till. "
             "The quotation can later be settled back into the POS for payment.",
    )

    def get_limited_partners_loading(self, offset=0):
        # The POS only preloads the most relevant partners; make sure the
        # configured default customer is always among them, mirroring what
        # l10n_ar_pos does for its anonymous "Consumidor Final" partner.
        partner_ids = super().get_limited_partners_loading(offset)
        default_partner = self.pos_retail_default_partner_id
        if default_partner and (default_partner.id,) not in partner_ids:
            partner_ids.append((default_partner.id,))
        return partner_ids

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

    def write(self, vals):
        """Never let a register be saved with an empty category restriction.

        "Restrict Available Categories" with nothing actually chosen compiles,
        server side, to `id in []` for categories (point_of_sale
        pos_category.py:45) and `pos_categ_ids in []` for products
        (product_template.py:79-80). The session payload then carries no
        categories and no products, and the register opens to a bare grid with
        no error anywhere -- the catalogue simply looks lost.

        _pos_retail_fix_empty_category_limit repairs databases already in that
        state, but it only runs on upgrade: without this, re-ticking the box in
        Settings without picking a category breaks the till again, silently.
        """
        res = super().write(vals)
        if 'limit_categories' in vals or 'iface_available_categ_ids' in vals:
            broken = self.filtered(
                lambda c: c.limit_categories and not c.iface_available_categ_ids)
            if broken:
                super(PosConfig, broken).write({'limit_categories': False})
        return res

    @api.model
    def _pos_retail_ensure_default_customer(self):
        """Point every register at a walk-in customer unless it names its own.

        Called from data/pos_retail_partner_tag_data.xml on install and upgrade,
        so it must stay idempotent. A register that already has a default is
        left alone -- this fills a blank, it does not impose a choice.
        """
        partner = self.env.ref(
            'pos_retail.partner_walk_in_customer', raise_if_not_found=False)
        if not partner:
            return
        if not partner.active:
            partner.sudo().write({'active': True})
        for config in self.sudo().search([('pos_retail_default_partner_id', '=', False)]):
            config.pos_retail_default_partner_id = partner.id

    @api.model
    def _pos_retail_fix_empty_category_limit(self):
        """Undo the setting combination that empties a register's product grid.

        Called from data/pos_retail_discount_reason_data.xml on install and
        upgrade, so it must stay idempotent.

        "Restrict Available Categories" with no categories actually chosen
        compiles to `pos_categ_ids in []`, which matches nothing: the register
        opens to a completely empty grid with no error anywhere, and the
        catalogue looks lost. It is never a deliberate configuration -- a shop
        that wants to sell nothing simply does not open the till -- so the
        restriction is switched back off. A register that names real categories
        is left exactly as it is.
        """
        broken = self.sudo().search([
            ('limit_categories', '=', True),
            ('iface_available_categ_ids', '=', False),
        ])
        for config in broken:
            config.limit_categories = False

    @api.model
    def _pos_retail_ensure_discount_product(self):
        """Guarantee every register has a product to carry order discounts.

        Called from data/pos_retail_discount_reason_data.xml on install and on
        every upgrade, so it must stay idempotent.

        The order-discount panel posts its discount as a line on a dedicated
        product, and reads it from pos.config.discount_product_id. That field
        belongs to pos_discount, which only fills it in when its own
        module_pos_discount toggle is on -- ours is a separate feature, so on a
        register where that toggle was never enabled the field stays empty and
        the panel can only report that the discount product is misconfigured.
        The shipped product is also archived on some databases, and an archived
        product never reaches the POS client.

        available_in_pos is deliberately left alone: pos_discount already loads
        this product through _get_special_products, and flagging it would put a
        sellable "Discount" tile in the product grid.
        """
        product = self.env.ref(
            'pos_discount.product_product_consumable', raise_if_not_found=False)
        if not product:
            return

        repairs = {}
        if not product.active:
            repairs['active'] = True
        if not product.sale_ok:
            repairs['sale_ok'] = True
        if repairs:
            product.sudo().write(repairs)

        # Registers with an open session are deliberately NOT skipped here, even
        # though pos_discount's own compute skips them. That caution is about
        # SWAPPING the product under a cashier who may already have discount
        # lines on an order; this pass only ever fills a field that is empty, so
        # there is no in-flight discount to disturb -- and skipping would leave
        # the panel broken on exactly the register someone is standing at.
        for config in self.sudo().search([('discount_product_id', '=', False)]):
            if product.company_id and product.company_id != config.company_id:
                continue
            config.discount_product_id = product.id

    @api.model
    def _pos_retail_seed_pricelists(self):
        """Offer the shipped customer-type pricelists at every unconfigured register.

        Called from data/pos_retail_pricelist_data.xml on install and on every
        upgrade, so it must stay idempotent and must never overrule a choice the
        store already made: a register that already lists any available pricelist
        is left exactly as it is.

        Only pricelists matching the register's own currency are attached --
        pos.config._check_currencies() rejects the write otherwise, and on a
        multi-currency tenant the shipped set belongs to the main company.
        """
        pricelists = self.env['product.pricelist'].browse([
            pricelist.id
            for xmlid in (
                'pos_retail.pricelist_retail',
                'pos_retail.pricelist_wholesale',
                'pos_retail.pricelist_dealer',
                'pos_retail.pricelist_distributor',
                'pos_retail.pricelist_vip',
                'pos_retail.pricelist_corporate',
            )
            if (pricelist := self.env.ref(xmlid, raise_if_not_found=False))
        ])
        if not pricelists:
            return

        default = self.env.ref('pos_retail.pricelist_retail', raise_if_not_found=False)

        for config in self.search([('available_pricelist_ids', '=', False)]):
            usable = pricelists.filtered(
                lambda p: p.currency_id == config.currency_id
                and (not p.company_id or p.company_id == config.company_id)
            )
            if not usable:
                continue
            config.write({
                'use_pricelist': True,
                'available_pricelist_ids': [fields.Command.set(usable.ids)],
                'pricelist_id': (default if default in usable else usable[0]).id,
            })


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    pos_retail_company_summary = fields.Char(
        string="Companies and Branches",
        compute='_compute_pos_retail_company_summary',
    )

    @api.depends_context('company')
    def _compute_pos_retail_company_summary(self):
        """Count companies and branches separately.

        Core counts every res.company row with an empty domain
        (base_setup/models/res_config_settings.py, _compute_company_count) and
        prints "3 Companies", while the Manage Companies action right beside it
        filters [('parent_id','=',False)] and lists ONE. Both numbers are
        defensible and together they are simply wrong: the shop has one company
        with two branches, and the screen says three of something and shows one
        of it.

        Counting the two separately is the only reading that matches what the
        owner actually has.
        """
        Company = self.env['res.company'].sudo()
        companies = Company.search_count([('parent_id', '=', False)])
        branches = Company.search_count([('parent_id', '!=', False)])
        label = "%s %s" % (companies, "Company" if companies == 1 else "Companies")
        if branches:
            label += ", %s %s" % (branches, "Branch" if branches == 1 else "Branches")
        for record in self:
            record.pos_retail_company_summary = label

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
    pos_retail_auto_product_barcode = fields.Boolean(
        related='company_id.pos_retail_auto_product_barcode',
        readonly=False,
        string="Generate Barcodes for New Products",
    )
    pos_retail_roundoff_step = fields.Float(
        related='pos_config_id.pos_retail_roundoff_step',
        readonly=False,
        string="Round-Off Step",
    )
    pos_retail_allow_quotation = fields.Boolean(
        related='pos_config_id.pos_retail_allow_quotation',
        readonly=False,
        string="Allow Quotations",
    )
    pos_retail_default_partner_id = fields.Many2one(
        related='pos_config_id.pos_retail_default_partner_id',
        readonly=False,
        string="Default Customer",
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
        string="Show Product Code (SKU) on Receipt Lines",
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
        string="Receipt Terms & Conditions",
    )
