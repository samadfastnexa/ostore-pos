/** @odoo-module **/

import { patch } from "@web/core/utils/patch";
import { ProductCard } from "@point_of_sale/app/components/product_card/product_card";

// Odoo 19 shows no price at all on the POS product card, so everything here is
// additive. The card already receives the whole product.template record as a
// prop, so no prop changes are needed.
patch(ProductCard.prototype, {
    get posRetailPriceInfo() {
        const product = this.props.product;
        if (!product) {
            return null;
        }
        const format = this.env.utils.formatCurrency;
        const minimum = product.minimum_selling_price || 0;
        const maximum = product.mrp || 0;
        // A single bound is still a range (a floor with no ceiling, or vice
        // versa); only show the line when it actually constrains something.
        const hasRange = Boolean(minimum || maximum) && minimum !== maximum;

        let range = "";
        if (hasRange) {
            if (minimum && maximum) {
                range = `${format(minimum)} - ${format(maximum)}`;
            } else if (minimum) {
                range = `min ${format(minimum)}`;
            } else {
                range = `max ${format(maximum)}`;
            }
        }

        // Stock comes from the variants, which already carry qty_available;
        // the template-level rollup is not loaded on purpose (see
        // product_template._load_pos_data_fields).
        const variants = product.product_variant_ids || [];
        const qty = variants.reduce((sum, variant) => sum + (variant.qty_available || 0), 0);

        return {
            price: format(product.list_price || 0),
            hasRange,
            range,
            isStorable: Boolean(product.is_storable),
            qty,
        };
    },
});
