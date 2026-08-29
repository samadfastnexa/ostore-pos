/** @odoo-module **/

import { patch } from "@web/core/utils/patch";
import { _t } from "@web/core/l10n/translation";
import { PaymentScreen } from "@point_of_sale/app/screens/payment_screen/payment_screen";
import { accountTaxHelpers } from "@account/helpers/account_tax";

// Order-level discount, expressed the way this counter actually works: the
// cashier does not decide "20 off" or "10 percent", they decide "call it 180"
// while the customer is handing money over. So the amount tendered on the
// payment screen IS the input, and the shortfall against the bill IS the
// discount. One button, no typing beyond the cash figure that was going to be
// keyed in regardless.
//
// The discount itself is still a negative pos.order.line on
// config.discount_product_id built through the shared tax engine, exactly as
// before, so receipts, reports and the rescale-on-cart-change watcher keep
// working with no changes of their own.
patch(PaymentScreen.prototype, {
    // --- charge only what was handed over ------------------------------------

    /** Discount lines the cashier's rounding buttons put there, which are a
     *  separate mechanism (tax-free, deliberately) and must not be folded into
     *  the discount arithmetic below. */
    posRetailRoundingLines(order) {
        return (order.discountLines || []).filter((line) => line.pos_retail_is_roundoff);
    },

    /** Order-level discount already applied, as a positive magnitude. */
    posRetailAppliedDiscount(order) {
        return (order.discountLines || [])
            .filter((line) => !line.pos_retail_is_roundoff)
            .reduce((sum, line) => sum + Math.abs(line.price_subtotal_incl || 0), 0);
    },

    /**
     * How far the cash tendered falls short of the bill, or 0 when it does not.
     * This is what the button offers to write off.
     */
    get posRetailShortfall() {
        const order = this.currentOrder;
        if (!order) {
            return 0;
        }
        // Requires an actual payment line first. With nothing tendered the
        // whole bill is "outstanding", and a one-tap button offering to
        // discount 100% of an order is how a till gets emptied by accident.
        if (!order.payment_ids?.length) {
            return 0;
        }
        const short = order.remainingDue;
        if (!short || short <= 0 || this.pos.currency.isZero(short)) {
            return 0;
        }
        return short;
    },

    get posRetailShortfallLabel() {
        return this.env.utils.formatCurrency(this.posRetailShortfall);
    },

    async posRetailDiscountShortfall() {
        const order = this.currentOrder;
        const short = this.posRetailShortfall;
        if (!short) {
            return;
        }
        // Added to whatever was already discounted rather than replacing it:
        // prepare_global_discount_lines takes the TOTAL discount for the order,
        // and the existing lines get rewritten in place below. Passing the bare
        // shortfall would quietly undo an earlier discount on a second tap.
        const total = this.posRetailAppliedDiscount(order) + short;
        await this.posRetailApplyDiscountLines("fixed", total, order);
    },

    // --- the discount mechanism ----------------------------------------------

    // Cart subtotal excluding discount lines, used to convert a fixed discount
    // into an equivalent percentage for the native rescale-on-cart-change
    // watcher in posRetailApplyDiscountLines. Discount lines are identified the
    // way core does it (order.discountLines, i.e. product is the discount
    // product); the previous `line.isDiscountLine` test named a property that
    // does not exist on the line model, so it was always undefined and every
    // discount line counted itself into the subtotal it was discounting.
    posRetailComputeSubtotal(order) {
        const discountLines = order.discountLines || [];
        return (order.lines || [])
            .filter((line) => !discountLines.includes(line))
            .reduce((sum, line) => sum + (line.price_subtotal_incl || 0), 0);
    },

    async posRetailApplyDiscountLines(kind, amount, order) {
        const taxKey = (taxIds) => taxIds.map((tax) => tax.id).sort((a, b) => a - b).join("_");
        const product = this.pos.config.discount_product_id;
        if (!product) {
            this.notification.add(
                _t(
                    "The discount product seems misconfigured. Make sure it is flagged as 'Can be Sold' and 'Available in Point of Sale'."
                ),
                { type: "danger" }
            );
            return;
        }

        // Rounding lines live on the same product, so they would collide in the
        // map below and be overwritten by a discount line sharing their (empty)
        // tax key. Held aside and left alone.
        const roundingLines = this.posRetailRoundingLines(order);
        const discountLinesMap = {};
        (order.discountLines || [])
            .filter((line) => !roundingLines.includes(line))
            .forEach((line) => {
                discountLinesMap[taxKey(line.tax_ids)] = line;
            });

        const lines = order.getOrderlines();
        const discountableLines = lines.filter((line) => line.isGlobalDiscountApplicable());
        const baseLines = discountableLines.map((line) =>
            accountTaxHelpers.prepare_base_line_for_taxes_computation(
                line,
                line.prepareBaseLineForTaxesComputationExtraValues()
            )
        );
        accountTaxHelpers.add_tax_details_in_base_lines(baseLines, order.company_id);
        accountTaxHelpers.round_base_lines_tax_details(baseLines, order.company_id);

        const groupingFunction = () => ({
            grouping_key: { product_id: product },
            raw_grouping_key: { product_id: product.id },
        });

        const globalDiscountBaseLines = accountTaxHelpers.prepare_global_discount_lines(
            baseLines,
            order.company_id,
            kind === "fixed" ? "fixed" : "percent",
            amount,
            { computation_key: "pos_retail_order_discount", grouping_function: groupingFunction }
        );

        // Store an equivalent percentage on the line so the native
        // rescale-on-cart-change watcher (keyed off order.globalDiscountPc,
        // patched by pos_discount) keeps this discount proportional too.
        const subtotal = this.posRetailComputeSubtotal(order);
        const percentForRescale =
            kind === "fixed" ? (subtotal ? (amount / subtotal) * 100 : 0) : amount;

        for (const baseLine of globalDiscountBaseLines) {
            const extra_tax_data = accountTaxHelpers.export_base_line_extra_tax_data(baseLine);
            extra_tax_data.discount_percentage = percentForRescale;

            const key = taxKey(baseLine.tax_ids);
            const existingLine = discountLinesMap[key];
            if (existingLine) {
                existingLine.extra_tax_data = extra_tax_data;
                existingLine.price_unit = baseLine.price_unit;
                delete discountLinesMap[key];
            } else {
                await this.pos.addLineToOrder(
                    {
                        product_id: baseLine.product_id,
                        price_unit: baseLine.price_unit,
                        qty: baseLine.quantity,
                        tax_ids: [["link", ...baseLine.tax_ids]],
                        product_tmpl_id: baseLine.product_id.product_tmpl_id,
                        extra_tax_data: extra_tax_data,
                    },
                    order,
                    { force: true },
                    false
                );
            }
        }

        Object.values(discountLinesMap).forEach((line) => line.delete());
    },
});
