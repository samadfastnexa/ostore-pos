from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tools import groupby


class ProductProduct(models.Model):
    _inherit = 'product.product'

    def write(self, vals):
        # standard_price is the real, stored, company-dependent field here;
        # product.template's own standard_price is only compute+inverse, and
        # its inverse performs a plain (non-sudo) write() on the variant, so
        # guarding here also catches that path -- not just direct variant
        # edits. See product_template.py for the matching list_price guard
        # and the full reasoning (both mirror account.move.write()'s own
        # "posted move" field lock, the closest core precedent for this).
        if ('standard_price' in vals
                and not self.env.su
                and not self.env.user._is_system()
                and not self.env.user._pos_retail_can_edit_price_field('standard_price')
                # No-op tolerance: only raise when the value actually changes.
                # The web client and load()/imports re-send unchanged fields;
                # blocking those would break e.g. re-importing a product CSV
                # whose Cost column is untouched.
                and any(p.standard_price != vals['standard_price'] for p in self)):
            raise AccessError(_(
                "You are not allowed to change the Cost on a product that "
                "already exists. Ask your administrator for the "
                "\"Can Edit Cost\" permission."
            ))
        return super().write(vals)

    # ------------------------------------------------------------------
    # Generated barcodes
    #
    # On the variant, not the template: product.template.barcode is only a
    # compute+inverse onto product_variant_ids (product_template.py:152 in
    # core), so a product with four sizes has four barcodes and one template
    # field that cannot represent them. Generating here gives every size its
    # own code, which is what a scanner needs.
    # ------------------------------------------------------------------

    @api.model_create_multi
    def create(self, vals_list):
        """Give a new product a barcode when none was scanned or typed.

        Most hardware and sanitary goods have nothing printed on them, so the
        alternative is the shopkeeper inventing a number per product before
        any shelf label can be printed.

        Only ever fills a BLANK barcode. A real manufacturer's code, whether
        scanned into the form or supplied by the import sheet, always wins --
        overwriting it would mean the printed code on the box no longer
        matches the one in Odoo, and the product silently stops scanning.

        Skipped entirely while a product.template is being created: the
        template's barcode inverse would read our generated code back off the
        variant and write it over the user's own. product_template.create()
        sets pos_retail_defer_barcode for that window and fills the blanks
        itself once the dust settles. This path still covers variants born
        later -- a new size added to an existing product.
        """
        if (self.env.company.pos_retail_auto_product_barcode
                and not self.env.context.get('pos_retail_defer_barcode')):
            for vals in vals_list:
                if not vals.get('barcode'):
                    vals['barcode'] = self._pos_retail_next_free_product_barcode()
        return super().create(vals_list)

    @api.model
    def _pos_retail_globalize_sequences(self):
        """Force the module's sequences to be company-agnostic.

        Called from data/pos_retail_package_data.xml on every install and
        upgrade. The sequence records themselves are noupdate (so numbering is
        never reset), but databases that installed an older version hold them
        scoped to whichever company loaded the module -- ir.sequence's own
        default. next_by_code() only matches the active company or global
        sequences, so in a multi-company database every OTHER company got
        "sequence is missing" instead of a barcode. Idempotent; touches only
        company_id.
        """
        self.env['ir.sequence'].sudo().search([
            ('code', 'in', [
                'pos.retail.product.barcode',
                'pos.retail.package.barcode',
                'pos.retail.vendor.code',
            ]),
            ('company_id', '!=', False),
        ]).write({'company_id': False})

    @api.model
    def _pos_retail_next_free_product_barcode(self):
        """A generated EAN-13 that no product and no package already uses.

        Checks both models because product.uom carries barcodes too and the
        till resolves a scan against both: a code shared between a product and
        a package would ring up whichever the scanner matched first.
        """
        sequence = self.env['ir.sequence']
        Package = self.env['product.uom']
        # Generous retry budget, matching the package generator: a stretch of
        # the range can already be taken -- typically after an import that
        # supplied its own 298-prefixed codes -- and skipping past it costs
        # nothing but sequence numbers.
        for _attempt in range(100):
            body = sequence.next_by_code('pos.retail.product.barcode')
            if not body:
                raise UserError(_(
                    "The product barcode sequence is missing. Upgrade the POS "
                    "Retail module to restore it, or type a barcode by hand."))
            candidate = Package._pos_retail_ean13(body)
            taken = self.sudo().search_count([('barcode', '=', candidate)]) or \
                Package.sudo().search_count([('barcode', '=', candidate)])
            if not taken:
                return candidate
        raise UserError(_(
            "Could not generate a free barcode after several tries. Check the "
            "product barcode sequence for clashes."))

    def action_pos_retail_generate_barcode(self):
        """Fill in a barcode for the selected products that have none.

        For catalogues imported before this was switched on, and for the rows
        left blank on purpose that now need a shelf label. Existing barcodes
        are never touched: they may already be printed and stuck to stock.
        """
        filled = 0
        for product in self:
            if not product.barcode:
                product.barcode = self._pos_retail_next_free_product_barcode()
                filled += 1
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'type': 'success' if filled else 'info',
                'message': (
                    _("Generated %s barcode(s).", filled) if filled else
                    _("Every product selected already has a barcode.")),
                'next': {'type': 'ir.actions.act_window_close'},
            },
        }

    @api.model
    def _load_pos_data_fields(self, config):
        result = super()._load_pos_data_fields(config)
        # Mirror of the template loader: the variant path needs the same selling
        # range so a price entered against a specific variant is validated too.
        for field in ('brand_id', 'qty_available', 'minimum_selling_price', 'mrp'):
            if field not in result:
                result.append(field)
        return result

    def _select_seller(self, partner_id=False, quantity=0.0, date=None, uom_id=False,
                        ordered_by='price_discounted', params=False):
        # Full override (not super()+tweak) of product.product._select_seller.
        # Base Odoo's "lock onto first vendor, then sort" logic is one inline
        # block with no seam to inject a narrowing step. Reused verbatim below;
        # the ONLY behavioral delta from stock Odoo is the `preferred` filter
        # applied to the candidate pool before that loop — a product with no
        # preferred vendor behaves byte-for-byte like stock Odoo.
        sort_key = ('price_discounted', 'sequence', 'id')
        if ordered_by != 'price_discounted':
            sort_key = (ordered_by, 'price_discounted', 'sequence', 'id')

        def sort_function(record):
            vals = {
                'price_discounted': record.currency_id._convert(
                    record.price_discounted,
                    record.env.company.currency_id,
                    record.env.company,
                    date or fields.Date.context_today(self),
                    round=False,
                ),
            }
            return [vals.get(key, record[key]) for key in sort_key]

        sellers = self._get_filtered_sellers(
            partner_id=partner_id, quantity=quantity, date=date, uom_id=uom_id, params=params,
        )
        preferred = sellers.filtered('is_preferred')
        if preferred:
            sellers = preferred

        res = self.env['product.supplierinfo']
        for seller in sellers:
            if not res or res.partner_id == seller.partner_id:
                res |= seller
        return res and res.sorted(sort_function)[:1]

    def _get_default_codes_by_company(self):
        return [
            (company_id, [p.default_code for p in products if p.default_code])
            for company_id, products in groupby(self, lambda p: p.company_id.id)
        ]

    def _check_duplicated_default_codes(self, codes_within_company, company_id):
        if not codes_within_company:
            return
        domain = [('default_code', 'in', codes_within_company)]
        if company_id:
            domain.append(('company_id', 'in', (False, company_id)))
        products_by_code = self.sudo()._read_group(
            domain, ['default_code'], ['id:recordset'], having=[('__count', '>', 1)],
        )
        duplicates_as_str = "\n".join(
            _("- SKU \"%(sku)s\" already assigned to product(s): %(product_list)s",
              sku=code, product_list=duplicate_products._filtered_access('read').mapped('display_name'))
            for code, duplicate_products in products_by_code
        )
        if duplicates_as_str:
            raise ValidationError(_(
                "Internal Reference(s) (SKU) already assigned:\n\n%s", duplicates_as_str
            ))

    @api.constrains('default_code')
    def _check_default_code_uniqueness(self):
        for company_id, codes_within_company in self._get_default_codes_by_company():
            self._check_duplicated_default_codes(codes_within_company, company_id)

    @api.constrains('standard_price')
    def _check_standard_price_non_negative(self):
        for product in self:
            if product.standard_price < 0:
                raise ValidationError(_("Cost Price must be zero or greater."))
