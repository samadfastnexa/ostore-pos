/** @odoo-module **/

import { patch } from "@web/core/utils/patch";
import { ProductCard } from "@point_of_sale/app/components/product_card/product_card";

// Odoo 19 shows no price at all on the POS product card, so everything here is
// additive. The card already receives the whole product.template record as a
// prop, so no prop changes are needed.
patch(ProductCard.prototype, {
    // What the till will ACTUALLY charge for one unit.
    //
    // This used to print product.list_price straight out, which ignored both
    // the customer's pricelist and tax: the grid said 200.00 Rs. while the cart
    // rang up 230.00 Rs. on a 15% tax-included register, and a wholesale
    // customer saw the retail figure. A cashier quoting from the grid quoted
    // the wrong number.
    //
    // getTaxDetails does the whole job -- pricelist, fiscal position, then the
    // tax engine -- but only if the pricelist is handed to it. Core's own
    // displayPriceUnit getter leaves it at false, so it cannot be reused here.
    posRetailCardPrice(product, format) {
        const fallback = () => format(product.list_price || 0);
        const pos = this.env.services?.pos;
        if (!pos || typeof product.getTaxDetails !== "function") {
            return fallback();
        }
        try {
            const order = pos.getOrder?.();
            const details = product.getTaxDetails({
                pricelist: order?.pricelist_id || pos.config?.pricelist_id || false,
                fiscalPosition: order?.fiscal_position_id || false,
            });
            const amount = pos.config?.iface_tax_included === "total"
                ? details.total_included
                : details.total_excluded;
            return Number.isFinite(amount) ? format(amount) : fallback();
        } catch {
            // A price the cashier can read beats a card that fails to render.
            return fallback();
        }
    },

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

        // "Rs 200" and "Rs 200 / m" are different offers. Pipe priced by the
        // metre next to a tap priced each, with no unit shown on either, is how
        // a cashier quotes the wrong figure. Suppressed for pieces, where the
        // unit adds nothing and the grid is tight.
        const measured = product.pos_retail_measurement_type
            && product.pos_retail_measurement_type !== "piece";
        const uom = measured ? product.uom_id?.name || "" : "";

        return {
            price: this.posRetailCardPrice(product, format),
            uom,
            priceSuffix: uom ? ` / ${uom}` : "",
            hasRange,
            range,
            isStorable: Boolean(product.is_storable),
            qty,
            // Stock in the unit it is actually counted in: "125 m", not "125".
            qtyLabel: uom ? `${qty} ${uom}` : String(qty),
        };
    },
});
