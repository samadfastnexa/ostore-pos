/** @odoo-module **/

import { patch } from "@web/core/utils/patch";
import { _t } from "@web/core/l10n/translation";
import { PaymentScreen } from "@point_of_sale/app/screens/payment_screen/payment_screen";
import { accountTaxHelpers } from "@account/helpers/account_tax";
import { onMounted } from "@odoo/owl";

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
    setup() {
        super.setup(...arguments);
        // NOT a wrap-and-reassign of this.onMounted: core's own setup(), just
        // called by super above, already did `onMounted(this.onMounted)`, and
        // that call captured the ORIGINAL method as a plain value there and
        // then -- reassigning this.onMounted afterwards, as a first attempt
        // here did, changes a property OWL had already stopped looking at, so
        // the replacement silently never ran. (Caught the same way as the
        // pricing bug below: by reading live state in a real browser rather
        // than trusting the code should work.)
        //
        // OWL runs any number of onMounted() registrations in the order they
        // were made, so a plain second registration -- AFTER super.setup(),
        // hence after core's own -- achieves the same ordering with no
        // reassignment for a hook to miss.
        onMounted(() => this.posRetailReconcileCampaignDiscount());
    },

    // --- the brand campaign, folded into the same one discount line ----------

    /**
     * Make sure the bill already reflects any live brand campaign the moment
     * the cashier reaches Payment -- not only when they choose to discount
     * something themselves.
     *
     * Runs on every arrival at this screen, which is what lets it recover from
     * the one case a single up-front calculation cannot: the cashier goes back
     * to add one more item, or a supplier's window happens to end mid-shift,
     * after money was already taken off this same order once before.
     *
     * The two amounts are added, never replaced: pos_retail_manualDiscount is
     * ONLY ever set by posRetailDiscountShortfall below, so a bill nobody has
     * touched carries the campaign's share alone, and a bill the cashier has
     * already discounted keeps that on top of whatever the campaign
     * contributes today.
     */
    async posRetailReconcileCampaignDiscount() {
        const order = this.currentOrder;
        if (!order) {
            return;
        }
        const campaignAmount = this.pos.posRetailCampaignDiscountAmount(order);
        const manual = order.pos_retail_manualDiscount || 0;
        const total = campaignAmount + manual;
        const current = this.posRetailAppliedDiscount(order);
        if (this.pos.currency.isZero(total - current)) {
            return; // already correct -- avoid rewriting lines for nothing
        }
        if (this.pos.currency.isZero(total) && current) {
            // The only discount left standing was the campaign's, and it just
            // ran out (or the line that earned it was removed) -- take the
            // line away rather than leave a 0.00 "Discount" on the receipt.
            for (const line of order.discountLines || []) {
                if (!this.posRetailRoundingLines(order).includes(line)) {
                    order.removeOrderline(line);
                }
            }
            return;
        }
        if (total > 0) {
            await this.posRetailApplyDiscountLines("fixed", total, order);
        }
    },

    // --- charge only what was handed over ------------------------------------

    /** Discount lines the cashier's rounding buttons put there, which are a
     *  separate mechanism (tax-free, deliberately) and must not be folded into
     *  the discount arithmetic below. */
    posRetailRoundingLines(order) {
        return (order.discountLines || []).filter((line) => line.pos_retail_is_roundoff);
    },

    /**
     * What one order line is actually worth right now, tax included.
     *
     * Reads order.prices.baseLineByLineUuids -- the live, tax-correct,
     * dirty-checked cache pos_order_accounting.js computes on demand, whose
     * own docstring says plainly: "These getters must be used each time the
     * order prices are needed. Do not try to make your own price computation
     * outside these getters."
     *
     * Three call sites in this file used to read line.price_subtotal_incl
     * directly instead. That field is real, but it is only ever WRITTEN by
     * setOrderPrices(), "called when the order is pushed to the backend" --
     * i.e. at validation. On a draft order still being shopped it is simply
     * undefined, so every one of those three computations silently evaluated
     * to zero the entire time it actually mattered: the running discount
     * total, the reclaimed rounding amount, and the cart subtotal used to
     * store a rescale percentage.
     *
     * It went unnoticed for as long as a discount line could only ever exist
     * because the cashier had just put one there themselves -- "add to
     * whatever was already discounted" and "replace it" look identical when
     * what was already discounted reads as zero either way. A live brand
     * campaign is the first thing that can ALSO leave a discount line on the
     * order before the cashier does anything, and it exposed the bug at
     * once: tapping "Discount the rest" on top of a running campaign
     * REPLACED the campaign's amount with the shortfall alone, and the
     * campaign's own discount silently vanished from the receipt. Caught by
     * reading a live order in a real browser, where the two numbers plainly
     * did not add up -- not by re-reading this code and trusting the comment
     * above it.
     */
    posRetailLineAmount(order, line) {
        return order.prices?.baseLineByLineUuids?.[line.uuid]?.tax_details?.total_included || 0;
    },

    /** Order-level discount already applied, as a positive magnitude. */
    posRetailAppliedDiscount(order) {
        return (order.discountLines || [])
            .filter((line) => !line.pos_retail_is_roundoff)
            .reduce((sum, line) => sum + Math.abs(this.posRetailLineAmount(order, line)), 0);
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
        // Fold any rounding adjustment into this discount instead of leaving
        // it beside one. Rounding down to 225 and then writing off the rest of
        // a 200 payment used to print TWO "Discount" lines on the receipt
        // (-5.00 and -25.00), which is arithmetically right and reads as a
        // mistake to the customer holding it. One line saying -30.00 says the
        // same thing.
        //
        // The rounding line's own amount has to be added back, because
        // removing it raises the total again: with a -5 rounding line the
        // shortfall was measured against 225, and once it goes the bill is 230
        // once more, so reaching 200 needs 25 + 5.
        let absorbed = 0;
        for (const line of this.posRetailRoundingLines(order)) {
            absorbed += -this.posRetailLineAmount(order, line);
            order.removeOrderline(line);
        }

        // Added to whatever was already discounted rather than replacing it:
        // prepare_global_discount_lines takes the TOTAL discount for the order,
        // and the existing lines get rewritten in place below. Passing the bare
        // shortfall would quietly undo an earlier discount on a second tap.
        const total = this.posRetailAppliedDiscount(order) + short + absorbed;
        await this.posRetailApplyDiscountLines("fixed", total, order);

        // Remember the part of `total` that was the cashier's own doing, apart
        // from any live brand campaign, so that if the cart changes again after
        // this tap -- one more item added, a supplier's window ending mid-sale
        // -- posRetailReconcileCampaignDiscount can rebuild the line as
        // "today's campaign share + this", instead of either doubling up on
        // the campaign or losing what was just written off.
        const campaignAmount = this.pos.posRetailCampaignDiscountAmount(order);
        order.pos_retail_manualDiscount = Math.max(0, total - campaignAmount);
    },

    // --- the discount mechanism ----------------------------------------------

    // Cart subtotal excluding discount lines, used to convert a fixed discount
    // into an equivalent percentage for the native rescale-on-cart-change
    // watcher in posRetailApplyDiscountLines. Discount lines are identified the
    // way core does it (order.discountLines, i.e. product is the discount
    // product); the previous `line.isDiscountLine` test named a property that
    // does not exist on the line model, so it was always undefined and every
    // discount line counted itself into the subtotal it was discounting.
    //
    // Also used to always read 0 for the same reason documented on
    // posRetailLineAmount above -- meaning percentForRescale below was always
    // computed as 0, and every fixed discount this file ever applied was
    // silently invisible to pos_discount's own rescale-on-cart-change watcher
    // (it treats globalDiscountPc = 0 as "no discount to rescale" and does
    // nothing). Not something a shortfall discount likely wants rescaled
    // anyway -- "knock 60 rupees off" does not obviously scale when another
    // item is added -- so the practical effect was harmless, but it was not
    // what either this comment or that one claimed was happening.
    posRetailComputeSubtotal(order) {
        const discountLines = order.discountLines || [];
        return (order.lines || [])
            .filter((line) => !discountLines.includes(line))
            .reduce((sum, line) => sum + this.posRetailLineAmount(order, line), 0);
    },

    async posRetailApplyDiscountLines(kind, amount, order) {
        const taxKey = (taxIds) => taxIds.map((tax) => tax.id).sort((a, b) => a - b).join("_");
        const product = this.pos.config.discount_product_id;
        if (!product) {
            // The old wording was pos_discount's: "seems misconfigured ...
            // flagged as 'Can be Sold' and 'Available in Point of Sale'". It
            // sent a live shop hunting through product flags when the field
            // is simply empty -- and on a working database that product has
            // Available in Point of Sale switched OFF, so the advice pointed
            // at a setting that must NOT be changed. Say what is actually
            // wrong and where it is set.
            this.notification.add(
                _t(
                    "This register has no discount product set, so a discount cannot be added to the order. Set one under Point of Sale > Configuration > Settings, then reopen the register."
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
