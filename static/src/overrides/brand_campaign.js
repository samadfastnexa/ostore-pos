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
    /**
     * The product every discount line is rung up on, found however it can be.
     *
     * Both discounts this shop gives -- the cashier knocking money off, and a
     * brand campaign running to a date -- write onto this one product, so
     * when it cannot be found NEITHER works. That is what a live till hit
     * while every server-side check passed: config.discount_product_id set,
     * product active and sellable, and the template, the variant AND the
     * config field all measurably reaching the payload, loaded as the till
     * user without sudo. The relation still came back empty in the browser.
     *
     * So take the id the server demonstrably sends and look the record up.
     * `raw` is core's own accessor for the unresolved server value --
     * pos_config.js reads this.raw.invoice_journal_id exactly this way -- so
     * this is a documented path, not a way around the model layer.
     */
    posRetailDiscountProduct() {
        return (
            this.config.discount_product_id ||
            (this.config.raw?.discount_product_id
                ? this.models["product.product"].get(this.config.raw.discount_product_id)
                : undefined)
        );
    },

    /**
     * The order's discount lines, resilient to the same failure.
     *
     * Core's own getter is `line.product_id.id === this.config.discount_product_id?.id`
     * (pos_order.js). When that relation is empty the comparison is against
     * undefined, so it matches nothing and returns [] -- which reads as "no
     * discount on this order" and makes every "replace the existing discount"
     * path add a second line instead. Same resolution, so the same answer
     * whichever way the relation went.
     */
    posRetailDiscountLines(order) {
        const product = this.posRetailDiscountProduct();
        if (!order || !product) {
            return [];
        }
        return (order.lines || []).filter((line) => line.product_id?.id === product.id);
    },

    /** Promotions whose window covers this MOMENT, at THIS branch.
     *
     *  Compared against the clock, not against midnight: the shop can start
     *  an offer at 6pm or end it at closing time, and rounding either end to
     *  a whole day would run it early and leave it running late. */
    get posRetailLiveCampaigns() {
        const model = this.models["pos.retail.brand.campaign"];
        if (!model) {
            return [];
        }
        const now = new Date();
        return model.getAll().filter((promo) => {
            if (promo.active === false) {
                return false;
            }
            const start = promo.date_start ? new Date(promo.date_start) : null;
            const end = promo.date_end ? new Date(promo.date_end) : null;
            return (!start || start <= now) && (!end || end >= now);
        });
    },

    /**
     * product.template id -> the promotion that wins for it.
     *
     * "Wins" rather than "all of them applied": two offers covering the same
     * item at once is not something a shop asks for, and adding them together
     * would discount further than either promise. Compared on what each is
     * actually worth for one unit at the CURRENT price, because that is the
     * only way to rank a percentage against a flat amount against a fixed
     * price without pretending they are the same kind of number.
     */
    posRetailCampaignFor(tmplId, unitPrice) {
        let best = null;
        let bestOff = 0;
        for (const promo of this.posRetailLiveCampaigns) {
            if (!(promo._product_tmpl_ids || []).includes(tmplId)) {
                continue;
            }
            const off = this.posRetailUnitDiscount(promo, unitPrice);
            if (off > bestOff) {
                best = promo;
                bestOff = off;
            }
        }
        return best ? { promo: best, unitOff: bestOff } : null;
    },

    /**
     * What one promotion takes off ONE unit at a given price.
     *
     * A fixed selling price is expressed as the difference from the normal
     * price, not by rewriting the line: the receipt then shows what the item
     * normally costs and what was saved, which is the whole reason this shop
     * wanted one combined discount line rather than quietly cheaper prices.
     * Never negative -- an offer that would RAISE a price is not an offer, so
     * it takes nothing off rather than charging extra.
     */
    posRetailUnitDiscount(promo, unitPrice) {
        const value = promo.discount_value || 0;
        if (value <= 0) {
            return 0;
        }
        if (promo.discount_type === "percent") {
            return (unitPrice || 0) * (value / 100);
        }
        if (promo.discount_type === "amount") {
            return Math.min(value, unitPrice || 0);
        }
        if (promo.discount_type === "fixed_price") {
            return Math.max(0, (unitPrice || 0) - value);
        }
        return 0;
    },

    /** What the catalogue badge should say for a product, or "" for none.
     *
     *  Takes a product.template -- what the ProductCard is actually given
     *  (see product_card.js's own comment) -- so `product.id` IS the template
     *  id already; no `.product_tmpl_id` hop, unlike an order line's
     *  product.product variant. */
    posRetailCampaignBadge(product) {
        if (!product) {
            return "";
        }
        const price = product.list_price ?? product.lst_price ?? 0;
        const hit = this.posRetailCampaignFor(product.id, price);
        if (!hit) {
            return "";
        }
        const promo = hit.promo;
        if (promo.discount_type === "percent") {
            return `${promo.discount_value}% OFF`;
        }
        if (promo.discount_type === "fixed_price") {
            return this.env.utils.formatCurrency(promo.discount_value);
        }
        return `${this.env.utils.formatCurrency(promo.discount_value)} OFF`;
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
        if (!order || !this.posRetailLiveCampaigns.length) {
            return 0;
        }
        const discountLines = this.posRetailDiscountLines(order);
        const byUuid = order.prices?.baseLineByLineUuids || {};
        let amount = 0;
        for (const line of order.lines || []) {
            if (discountLines.includes(line)) {
                continue; // never discount a discount line
            }
            const tmplId = line.product_id?.product_tmpl_id?.id;
            if (!tmplId) {
                continue;
            }
            const qty = line.getQuantity ? line.getQuantity() : line.qty || 0;
            if (qty <= 0) {
                continue; // a refund line is not an opportunity to discount
            }
            // Per UNIT, at the price actually being charged on this line --
            // not the catalogue price. The cashier may have keyed a different
            // figure through the price popup, and a promotion has to come off
            // what the customer is really being asked to pay, or a percentage
            // and a fixed price disagree about the same sale.
            const lineTotal = byUuid[line.uuid]?.tax_details?.total_included || 0;
            const unitPrice = lineTotal / qty;
            const hit = this.posRetailCampaignFor(tmplId, unitPrice);
            if (hit) {
                amount += hit.unitOff * qty;
            }
        }
        return amount;
    },
});
