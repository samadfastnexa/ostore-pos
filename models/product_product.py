from odoo import _, api, fields, models
from odoo.exceptions import AccessError, ValidationError
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
