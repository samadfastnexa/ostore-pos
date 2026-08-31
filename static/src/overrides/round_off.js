/** @odoo-module **/

import { patch } from "@web/core/utils/patch";
import { _t } from "@web/core/l10n/translation";
import { PaymentScreen } from "@point_of_sale/app/screens/payment_screen/payment_screen";

// Rounding a bill to a whole cash figure, as the CASHIER's decision.
//
// Odoo's own cash rounding is a config setting: switch it on and every cash
// sale is rounded the same way, with no say at the counter. That is wrong for a
// shop where it depends on the customer -- one regular hands over 240 for a 238
// bill without blinking, the next one counts out exactly what is owed and would
// query the extra two rupees.
//
// So both figures are offered and the cashier picks, or picks neither. The
// adjustment is an ordinary order line on the discount product, priced at the
// difference: negative to round down, positive to round up. Rounding up through
// the global-discount helper is not possible -- it only ever discounts -- which
// is why this writes the line directly.
//
// The line is tax-free on purpose. A rounding of a couple of rupees is a
// goodwill adjustment to the cash total, not a sale of anything, and taxing it
// would leave the total off by the tax on the rounding itself.
patch(PaymentScreen.prototype, {
    /** The two whole figures either side of the current total, or null. */
    get posRetailRoundTargets() {
        const order = this.currentOrder;
        const step = this.pos.config.pos_retail_roundoff_step || 0;
        if (!order || step <= 0) {
            return null;
        }
        const total = order.totalDue;
        if (!total || total <= 0) {
            return null;
        }
        let down = Math.floor(total / step) * step;
        let up = Math.ceil(total / step) * step;

        // When the bill already sits on a step there is nothing to "round", so
        // this used to hide itself. That was wrong for this shop: the prices
        // are round numbers, so most bills land exactly on a multiple of the
        // step and the buttons almost never appeared. A control that shows up
        // occasionally, with no explanation when it does not, reads as broken,
        // and it was reported as missing three times.
        //
        // So on an exact total it offers one step either side instead: a 230
        // bill becomes "Round to 225" and "Round to 235". It stops being
        // strictly rounding and becomes a one-tap adjustment either way, which
        // is what a cashier haggling over the last few rupees actually wants.
        if (this.pos.currency.isZero(up - down)) {
            down = total - step;
            up = total + step;
        }

        // Never offer to take the bill to zero or below: that is a giveaway,
        // not a rounding, and it should go through the discount flow where the
        // amount is typed deliberately.
        const targets = {
            total,
            up,
            upLabel: this.env.utils.formatCurrency(up),
            upDiff: this.env.utils.formatCurrency(up - total),
        };
        if (down > 0) {
            targets.down = down;
            targets.downLabel = this.env.utils.formatCurrency(down);
            targets.downDiff = this.env.utils.formatCurrency(down - total);
        }
        return targets;
    },

    /** Whether this order already carries a rounding line. */
    get posRetailRoundOffLine() {
        return (this.currentOrder?.getOrderlines() || []).find(
            (line) => line.pos_retail_is_roundoff
        );
    },

    async posRetailRoundTo(target) {
        const order = this.currentOrder;
        const product = this.pos.config.discount_product_id;
        if (!product) {
            this.notification.add(
                _t("No discount product is set on this register, so there is nothing to carry the rounding."),
                { type: "danger" }
            );
            return;
        }

        // Replace rather than stack: rounding twice must not leave two lines.
        const existing = this.posRetailRoundOffLine;
        if (existing) {
            order.removeOrderline(existing);
        }

        // Recompute AFTER removing the old line, or the difference would be
        // measured against a total that still contains the previous rounding.
        const difference = target - order.totalDue;
        if (this.pos.currency.isZero(difference)) {
            return;
        }

        // If the order already carries an order-level discount and this is a
        // round DOWN, fold the two together rather than adding a second line.
        // Otherwise a customer who was given a discount and then had the bill
        // rounded reads "Discount" twice on the receipt for what is, to them,
        // one reduction. Rounding UP is not a discount at all, so it keeps its
        // own line -- prepare_global_discount_lines only ever discounts, and a
        // negative discount is not a thing it can express.
        const applied = this.posRetailAppliedDiscount(order);
        if (applied && difference < 0) {
            await this.posRetailApplyDiscountLines("fixed", applied - difference, order);
            return;
        }

        await this.pos.addLineToOrder(
            {
                product_id: product,
                product_tmpl_id: product.product_tmpl_id,
                price_unit: difference,
                qty: 1,
                price_type: "manual",
                tax_ids: [["clear"]],
                pos_retail_is_roundoff: true,
            },
            order,
            { force: true },
            false
        );
    },

    async posRetailClearRounding() {
        const line = this.posRetailRoundOffLine;
        if (line) {
            this.currentOrder.removeOrderline(line);
        }
    },
});
