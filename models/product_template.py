from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError, ValidationError


class ProductTemplate(models.Model):
    _inherit = 'product.template'

    # Odoo 19 ships product.template.categ_id with no default at all, so a
    # bulk import that does not carry a category column leaves every row
    # uncategorised -- which then breaks stock valuation grouping and every
    # category report. Supplying one here is what lets the five-column import
    # sheet leave the column out entirely.
    categ_id = fields.Many2one(
        default=lambda self: self.env.ref('product.product_category_goods',
                                          raise_if_not_found=False),
    )
    brand_id = fields.Many2one(
        'product.brand', string="Brand", index=True, ondelete='set null',
        help="Maker or brand this item is sold under, e.g. Nestle or Tapal. "
             "Used to group and filter products in the catalogue and reports; "
             "leave empty for loose or unbranded goods.",
    )
    wholesale_price = fields.Float(
        string="Wholesale Price", min_display_digits='Product Price',
        help="Price offered to wholesale/bulk buyers. Informational only — "
             "not enforced by any pricelist or sale/POS logic. To actually sell "
             "at this price, set up a Wholesale pricelist.",
    )
    minimum_selling_price = fields.Float(
        string="Minimum Selling Price", min_display_digits='Product Price',
        help="The lowest price this item may be sold at. A cashier may sell "
             "anywhere between this and the Maximum Retail Price without "
             "approval; below it a manager PIN is required. Leave at 0 to allow "
             "any price down to zero.",
    )
    mrp = fields.Float(
        string="Maximum Retail Price (MRP)", min_display_digits='Product Price',
        help="The highest price this item may be sold at — usually the price "
             "printed on the pack. Above it a manager PIN is required. Leave at "
             "0 for no upper limit.",
    )
    vendor_count = fields.Integer(
        string="# Vendors", compute='_compute_vendor_count', store=True,
        help="How many different vendors you have pricing set up for on the "
             "Vendors tab. Zero means nobody is set up to supply this item yet, "
             "so purchase orders will not suggest a price.",
    )

    discount_type = fields.Selection(
        [('percent', "Percentage"), ('fixed', "Fixed Amount")],
        string="Discount Type", default='percent',
        help="How to read the Discount Value beside it: as a percentage off the "
             "Selling Price, or as a flat amount off. It only feeds the Final "
             "Selling Price shown here; the till is not affected.",
    )
    discount_value = fields.Float(
        string="Discount Value", default=0.0,
        help="How much to knock off the Selling Price, read as a percentage or "
             "a fixed amount depending on the Discount Type. Leave at 0 for no "
             "discount.",
    )
    final_selling_price = fields.Monetary(
        string="Final Selling Price", currency_field='currency_id',
        compute='_compute_final_selling_price',
        help="Selling Price after applying the Discount Type/Value above. "
             "Informational only — not enforced by any pricelist, POS, or Sales Order logic.",
    )

    profit_amount = fields.Monetary(
        string="Profit Amount", currency_field='currency_id', compute='_compute_profit',
        help="What you make on one unit at the current Selling Price: the "
             "Selling Price less the Cost. A negative figure means you lose "
             "money on every one you sell.",
    )
    profit_margin_percent = fields.Float(
        string="Profit Margin %", compute='_compute_profit',
        help="The profit measured against what the item costs you, so 100% "
             "means you sell it for double the cost. Anything under 20% is "
             "flagged as a thin margin.",
    )
    has_selling_below_cost = fields.Boolean(
        compute='_compute_profit',
        help="Technical field: true when the Selling Price sits below the Cost. "
             "Used only to raise the loss-making warning on the product form.",
    )
    has_low_margin = fields.Boolean(
        compute='_compute_profit',
        help="Technical field: true when the item still makes a profit but the "
             "margin is under 20%. Used only to raise the thin-margin warning "
             "on the product form.",
    )
    has_min_selling_price_warning = fields.Boolean(
        compute='_compute_min_selling_price_warning',
        help="Technical field: true when the Minimum Selling Price has been set "
             "above the Selling Price. Used only to raise that warning on the "
             "product form.",
    )
    pos_retail_price_locked = fields.Boolean(
        compute='_compute_pos_retail_price_locked',
        help="Technical field: whether the current user is blocked from "
             "editing Sales Price on this already-saved product. A pure "
             "view-level hint -- the actual enforcement is the write() guard "
             "below; this only makes the field visibly read-only instead of "
             "letting the user discover the block after clicking Save.",
    )
    pos_retail_cost_locked = fields.Boolean(
        compute='_compute_pos_retail_price_locked',
        help="Same as pos_retail_price_locked, for the Cost field. Separate "
             "on purpose: a role can grant one of the two without the other.",
    )

    # Packages live on the variant (product.product.product_uom_ids); this
    # surfaces them on the template form, which is where shopkeepers work.
    # Only meaningful for single-variant products -- the Packages page is
    # hidden otherwise and those are managed on the variant itself.
    # Routed through product_variant_ids, NOT product_variant_id: the singular
    # field is a non-stored compute with no search method, so Odoo cannot work
    # out which templates to invalidate when a variant's packages change and
    # warns about it on every install. product_variant_ids is a real one2many
    # and therefore searchable. For the single-variant products this is used on
    # (the Packages page is hidden above one variant) the two resolve to the
    # same records.
    pos_retail_package_ids = fields.One2many(
        related='product_variant_ids.product_uom_ids', readonly=False,
        string="Packages",
        help="The pack sizes this item is also sold in, e.g. a 5 kg bag as well "
             "as loose kg. Each package has its own barcode and price, while "
             "stock is still counted in the product's own unit.",
    )

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

    @api.depends_context('uid')
    def _compute_pos_retail_price_locked(self):
        # One permission check per recordset render, not per record: whether
        # editing is locked doesn't vary record-to-record, only "is this
        # record new or already saved" does (a brand-new record in the form
        # is never locked -- create() is intentionally unrestricted).
        can_edit_price = self.env.user._pos_retail_can_edit_price_field('list_price')
        can_edit_cost = self.env.user._pos_retail_can_edit_price_field('standard_price')
        for tmpl in self:
            tmpl.pos_retail_price_locked = bool(tmpl.id) and not can_edit_price
            tmpl.pos_retail_cost_locked = bool(tmpl.id) and not can_edit_cost

    def write(self, vals):
        if ('list_price' in vals
                and not self.env.su
                and not self.env.user._is_system()
                and not self.env.user._pos_retail_can_edit_price_field('list_price')
                # No-op tolerance: only raise when the value actually changes.
                # The web client and load()/imports re-send unchanged fields;
                # blocking those would break e.g. re-importing a product CSV
                # whose Sales Price column is untouched.
                and any(t.list_price != vals['list_price'] for t in self)):
            raise AccessError(_(
                "You are not allowed to change the Sales Price on a product "
                "that already exists. Ask your administrator for the "
                "\"Can Edit Sales Price\" permission."
            ))
        return super().write(vals)

    @api.model
    def _load_pos_data_fields(self, config):
        # The POS product grid renders product.template records
        # (point_of_sale product_screen.xml), so the selling range has to travel
        # on the template for the card and the price popup to read it.
        # Deliberately NOT loading qty_available here: on the template it is a
        # computed rollup over every variant, and pulling it for the whole
        # catalogue slows session start. The variants already carry it (see
        # product_product._load_pos_data_fields), so the card sums those.
        result = super()._load_pos_data_fields(config)
        for field in ('minimum_selling_price', 'mrp'):
            if field not in result:
                result.append(field)
        return result

    @api.model_create_multi
    def create(self, vals_list):
        """Generate missing barcodes only once the template has settled.

        This has to happen here rather than in product.product.create(), and
        the reason is a trap in core.

        product.template.barcode is a non-stored compute+inverse onto the
        variant (product_template.py:152). The inverse is
        `_set_product_variant_field`, which does
        `template.product_variant_ids['barcode'] = template['barcode']` -- it
        reads the template field, which is itself COMPUTED FROM THE VARIANT.

        So during create the order is: variant row is created, then the
        inverse fires. Anything that writes a barcode onto the variant in
        between invalidates the template's cached value, the compute re-runs
        off the variant, and the inverse then writes that generated code
        straight back over the barcode the user actually typed. Silently.

        Hence the context flag: variant-level generation is suppressed for the
        duration of super(), and blanks are filled afterwards, by which point
        a scanned or imported barcode is safely in place and simply is not
        blank any more.

        The variant-level hook still runs for variants created later -- adding
        a size to an existing product -- where no template inverse is involved.
        """
        templates = super(
            ProductTemplate,
            self.with_context(pos_retail_defer_barcode=True),
        ).create(vals_list)
        templates._pos_retail_fill_missing_barcodes()
        return templates

    def _pos_retail_fill_missing_barcodes(self):
        """Give a scannable code to any variant still without one."""
        if not self.env.company.pos_retail_auto_product_barcode:
            return
        Variant = self.env['product.product']
        for variant in self.product_variant_ids:
            if not variant.barcode:
                variant.barcode = Variant._pos_retail_next_free_product_barcode()

    @api.model
    def get_import_templates(self):
        """Offer ready-made spreadsheets on the product Import screen.

        Deliberately does NOT call super(). Core's template
        (product/static/xls/product_product.xls) arrives pre-filled with Odoo's
        own demo catalogue -- Apple headphones, an iMac, Star Wars t-shirts --
        which a shop has to delete row by row before it can start, and it carries
        none of this module's fields. Returning only ours replaces it rather than
        offering both, so the Import screen has no wrong answer on it. Chain to
        super() here if you ever want core's back alongside.

        One file, every field, generated by tools/import_templates.py, served live by controllers/import_template.py.
        Splitting it into a short and a long version only made the Import screen
        ask a question before the work started; the sheet is ordered instead, so
        the nine columns that get a catalogue in come first and the rest trail
        off to the right where they can be left blank.
        """
        return [{
            # No column count in the label: it has been five, then twenty-three,
            # then eleven, and a stale number on the button is worse than none.
            'label': _("Download the Product List spreadsheet"),
            'template': '/pos_retail/import-template/product.xlsx',
        }]

    @api.constrains('list_price')
    def _check_list_price_non_negative(self):
        for tmpl in self:
            if tmpl.list_price < 0:
                raise ValidationError(_("Selling Price must be zero or greater."))

    @api.constrains('minimum_selling_price', 'mrp', 'list_price')
    def _check_selling_price_range(self):
        """Keep the selling range coherent: minimum <= default <= MRP.

        Each bound is optional -- 0 means "not set" -- so products that never had
        a range configured (the majority, since these fields used to be purely
        informational) stay valid and are simply unconstrained at the till.
        """
        for tmpl in self:
            minimum = tmpl.minimum_selling_price
            maximum = tmpl.mrp
            if minimum < 0 or maximum < 0:
                raise ValidationError(_(
                    "Minimum Selling Price and Maximum Retail Price (MRP) must "
                    "be zero or greater."
                ))
            if minimum and maximum and minimum > maximum:
                raise ValidationError(_(
                    "Minimum Selling Price (%(minimum).2f) cannot be greater than "
                    "the Maximum Retail Price (%(maximum).2f) for \"%(product)s\".",
                    minimum=minimum, maximum=maximum, product=tmpl.display_name,
                ))
            if minimum and tmpl.list_price and tmpl.list_price < minimum:
                raise ValidationError(_(
                    "The Selling Price (%(price).2f) of \"%(product)s\" is below its "
                    "Minimum Selling Price (%(minimum).2f).",
                    price=tmpl.list_price, minimum=minimum, product=tmpl.display_name,
                ))
            if maximum and tmpl.list_price and tmpl.list_price > maximum:
                raise ValidationError(_(
                    "The Selling Price (%(price).2f) of \"%(product)s\" is above its "
                    "Maximum Retail Price (%(maximum).2f).",
                    price=tmpl.list_price, maximum=maximum, product=tmpl.display_name,
                ))
