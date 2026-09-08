/** @odoo-module **/

import { patch } from "@web/core/utils/patch";
import { PosStore } from "@point_of_sale/app/services/pos_store";

// A supplier's own offer -- "Sonex, 10% off, for 15 days" -- applied by
// itself, with no cashier action, for as long as it is dated to run.
//
// Deliberately separate from the cashier's own discount (order_discount.js):
// that one is a decision made at the counter, one bill at a time. This one is
// an arrangement with a maker, and it has to behave the same way on every
// till, every day, without anyone remembering to switch it on or off. The two
// still end up on the SAME receipt line -- order_discount.js folds this
// amount in alongside whatever the cashier takes off, so the customer reads
// one "Discount", never one line per product.
//
// pos.retail.brand.campaign is loaded WITHOUT a date filter on the server
// (see the model's _load_pos_data_domain) precisely so that "today" can be
// evaluated here, live, every time it matters -- the same way core evaluates
// loyalty.program's date_from/date_to, rather than trusting a filtered list
// that a long-open session may never be told to refresh.
patch(PosStore.prototype, {
    /** Campaigns whose window actually covers today, at THIS branch. */
    get posRetailLiveCampaigns() {
        const model = this.models["pos.retail.brand.campaign"];
        if (!model) {
            return [];
        }
        const today = new Date();
        today.setHours(0, 0, 0, 0);
        return model.getAll().filter((campaign) => {
            const start = campaign.date_start ? new Date(campaign.date_start) : null;
            const end = campaign.date_end ? new Date(campaign.date_end) : null;
            return (!start || start <= today) && (!end || end >= today);
        });
    },

    /**
     * product.template id -> the best (largest) live discount percent for it.
     *
     * "Best" rather than "summed": two suppliers running campaigns on the same
     * item at once is not something this shop asked for, and adding them
     * together would silently discount a product further than either offer
     * actually promises. The customer gets the better of the two, not both.
     */
    get posRetailCampaignPercentByTemplate() {
        const map = new Map();
        for (const campaign of this.posRetailLiveCampaigns) {
            const pct = campaign.discount_percent || 0;
            if (pct <= 0) {
                continue;
            }
            for (const tmplId of campaign._product_tmpl_ids || []) {
                if (!map.has(tmplId) || map.get(tmplId) < pct) {
                    map.set(tmplId, pct);
                }
            }
        }
        return map;
    },

    /** The live campaign percent for one product, or 0 if none applies. Used
     *  by the catalogue badge so a cashier can see an offer before it is even
     *  on a bill.
     *
     *  Takes a product.template -- what the ProductCard is actually given
     *  (see product_card.js's own comment) -- so `product.id` IS the template
     *  id already; no `.product_tmpl_id` hop, unlike an order line's
     *  product.product variant. */
    posRetailCampaignPercentForProduct(product) {
        if (!product) {
            return 0;
        }
        return this.posRetailCampaignPercentByTemplate.get(product.id) || 0;
    },

    /**
     * The currency amount a live campaign takes off THIS order right now.
     *
     * Reads order.prices.baseLineByLineUuids -- the live, tax-correct,
     * dirty-checked price cache pos_order_accounting.js computes on demand and
     * whose own docstring says plainly: "These getters must be used each time
     * the order prices are needed. Do not try to make your own price
     * computation outside these getters."
     *
     * A first version read line.price_subtotal_incl instead, the same field
     * order_discount.js's posRetailComputeSubtotal already treats as "the
     * amount". That field is real, but pos_order_accounting.js's own
     * setOrderPrices() only ever WRITES it "when the order is pushed to the
     * backend" -- i.e. at validation. On a draft order still being shopped it
     * is simply undefined, so every line contributed (undefined || 0) * pct =
     * 0, and the campaign discount silently computed as zero for the entire
     * time it actually matters. Caught by reading window.posmodel's live state
     * from a real browser session rather than trusting the pattern by analogy.
     *
     * The result is handed to the existing
     * posRetailApplyDiscountLines("fixed", ...), which does the tax-correct
     * split across lines; this function only has to get the CURRENCY AMOUNT
     * right.
     */
    posRetailCampaignDiscountAmount(order) {
        if (!order) {
            return 0;
        }
        const percentByTemplate = this.posRetailCampaignPercentByTemplate;
        if (!percentByTemplate.size) {
            return 0;
        }
        const discountLines = order.discountLines || [];
        const byUuid = order.prices?.baseLineByLineUuids || {};
        let amount = 0;
        for (const line of order.lines || []) {
            if (discountLines.includes(line)) {
                continue; // never discount a discount line
            }
            const tmplId = line.product_id?.product_tmpl_id?.id;
            const pct = tmplId ? percentByTemplate.get(tmplId) : undefined;
            if (!pct) {
                continue;
            }
            const included = byUuid[line.uuid]?.tax_details?.total_included || 0;
            amount += included * (pct / 100);
        }
        return amount;
    },
});
