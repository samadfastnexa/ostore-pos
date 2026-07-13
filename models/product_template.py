from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError


class ProductTemplate(models.Model):
    _inherit = 'product.template'

    brand_id = fields.Many2one(
        'product.brand', string="Brand", index=True, ondelete='set null',
    )
    wholesale_price = fields.Float(
        string="Wholesale Price", min_display_digits='Product Price',
        help="Price offered to wholesale/bulk buyers. Informational only — "
             "not enforced by any pricelist or sale/POS logic.",
    )
    minimum_selling_price = fields.Float(
        string="Minimum Selling Price", min_display_digits='Product Price',
        help="Floor price below which this product should not normally be sold. "
             "Informational only — not enforced on POS/Sales Order lines.",
    )
    mrp = fields.Float(
        string="MRP", min_display_digits='Product Price',
        help="Maximum Retail Price printed on the package, if applicable. "
             "Informational only — not enforced by any pricelist or sale/POS logic.",
    )
    vendor_count = fields.Integer(
        string="# Vendors", compute='_compute_vendor_count', store=True,
    )

    discount_type = fields.Selection(
        [('percent', "Percentage"), ('fixed', "Fixed Amount")],
        string="Discount Type", default='percent',
    )
    discount_value = fields.Float(string="Discount Value", default=0.0)
    final_selling_price = fields.Monetary(
        string="Final Selling Price", currency_field='currency_id',
        compute='_compute_final_selling_price',
        help="Selling Price after applying the Discount Type/Value above. "
             "Informational only — not enforced by any pricelist, POS, or Sales Order logic.",
    )

    profit_amount = fields.Monetary(
        string="Profit Amount", currency_field='currency_id', compute='_compute_profit',
    )
    profit_margin_percent = fields.Float(string="Profit Margin %", compute='_compute_profit')
    has_selling_below_cost = fields.Boolean(compute='_compute_profit')
    has_low_margin = fields.Boolean(compute='_compute_profit')
    has_min_selling_price_warning = fields.Boolean(compute='_compute_min_selling_price_warning')

    linked_vendor_ids = fields.Many2many(
        'res.partner', compute='_compute_linked_vendor_ids', string="Linked Vendors",
        help="Technical field: vendors already linked via the Vendors tab below. "
             "Used only to restrict the Preferred Vendor selection.",
    )
    preferred_vendor_id = fields.Many2one(
        'res.partner', string="Preferred Vendor",
        compute='_compute_preferred_vendor_id', inverse='_inverse_preferred_vendor_id',
        help="Vendor whose Vendor Pricing row is flagged Preferred. Restricted to "
             "vendors already linked via the Vendors tab. Picking one here suggests "
             "that vendor's last purchase price as the Cost Price (you can still "
             "retype Cost Price before saving).",
    )

    @api.depends('seller_ids.partner_id')
    def _compute_vendor_count(self):
        for tmpl in self:
            tmpl.vendor_count = len(tmpl.seller_ids.partner_id)

    @api.depends('seller_ids.partner_id')
    def _compute_linked_vendor_ids(self):
        for tmpl in self:
            tmpl.linked_vendor_ids = tmpl.seller_ids.partner_id

    @api.depends('seller_ids.is_preferred', 'seller_ids.partner_id')
    def _compute_preferred_vendor_id(self):
        for tmpl in self:
            tmpl.preferred_vendor_id = tmpl.seller_ids.filtered('is_preferred')[:1].partner_id

    def _inverse_preferred_vendor_id(self):
        # Fires only at real write()/create() (Save) — never called from onchange.
        # Must NEVER touch tmpl.standard_price here; that's the onchange's job only,
        # otherwise a manual Cost Price retype after picking a vendor could be
        # clobbered at Save.
        for tmpl in self:
            current_preferred = tmpl.seller_ids.filtered('is_preferred')
            if not tmpl.preferred_vendor_id:
                current_preferred.write({'is_preferred': False})
                continue
            seller = tmpl.seller_ids.filtered(
                lambda s: s.partner_id == tmpl.preferred_vendor_id
            ).sorted('min_qty')[:1]  # single row only — see _enforce_single_preferred note
            if not seller:
                raise UserError(_(
                    "%(vendor)s has no Vendor Pricing entry for %(product)s yet. "
                    "Add one in the Vendors tab below before marking them Preferred.",
                    vendor=tmpl.preferred_vendor_id.display_name, product=tmpl.display_name,
                ))
            seller.write({'is_preferred': True})  # triggers _enforce_single_preferred

    @api.onchange('preferred_vendor_id')
    def _onchange_preferred_vendor_id(self):
        # Live, pre-save only. Only ever assigns self.standard_price (cache-only
        # while editing). Never calls .write() on seller_ids records here.
        for tmpl in self:
            if not tmpl.preferred_vendor_id:
                continue
            seller = tmpl.seller_ids.filtered(
                lambda s: s.partner_id == tmpl.preferred_vendor_id
            ).sorted('min_qty')[:1]
            if seller:
                tmpl.standard_price = seller.last_purchase_price or seller.price

    @api.depends('list_price', 'standard_price')
    def _compute_profit(self):
        for tmpl in self:
            tmpl.profit_amount = tmpl.list_price - tmpl.standard_price
            if tmpl.standard_price:
                tmpl.profit_margin_percent = (
                    (tmpl.list_price - tmpl.standard_price) / tmpl.standard_price * 100
                )
            else:
                tmpl.profit_margin_percent = 0.0
            tmpl.has_selling_below_cost = tmpl.list_price < tmpl.standard_price
            tmpl.has_low_margin = (
                not tmpl.has_selling_below_cost and tmpl.profit_margin_percent < 20.0
            )

    @api.depends('minimum_selling_price', 'list_price')
    def _compute_min_selling_price_warning(self):
        for tmpl in self:
            tmpl.has_min_selling_price_warning = (
                bool(tmpl.minimum_selling_price) and tmpl.minimum_selling_price > tmpl.list_price
            )

    @api.depends('list_price', 'discount_type', 'discount_value')
    def _compute_final_selling_price(self):
        for tmpl in self:
            if tmpl.discount_type == 'fixed':
                tmpl.final_selling_price = tmpl.list_price - tmpl.discount_value
            else:
                tmpl.final_selling_price = tmpl.list_price * (1 - tmpl.discount_value / 100.0)

    @api.constrains('list_price')
    def _check_list_price_non_negative(self):
        for tmpl in self:
            if tmpl.list_price < 0:
                raise ValidationError(_("Selling Price must be zero or greater."))
