/** @odoo-module **/

import { patch } from "@web/core/utils/patch";
import { _t } from "@web/core/l10n/translation";
import { PosStore } from "@point_of_sale/app/services/pos_store";
import { PosOrderline } from "@point_of_sale/app/models/pos_order_line";
import { OrderSummary } from "@point_of_sale/app/screens/product_screen/order_summary/order_summary";
import { SelectionPopup } from "@point_of_sale/app/components/popups/selection_popup/selection_popup";
import { makeAwaitable } from "@point_of_sale/app/utils/make_awaitable_dialog";
import { PriceSelectionPopup } from "./price_popup";
import { posRetailRequestManagerPin } from "../utils/manager_pin";

// Flexible pricing: ask for the selling price as a ranged product is added.
//
// The hook is addLineToCurrentOrder rather than ProductScreen.addProductToOrder
// because the store method is the single funnel for card taps, barcode scans and
// GS1 scans alike, so scanning a ranged product is validated exactly like
// tapping it.
patch(PosStore.prototype, {
    /** A product is "ranged" only when a bound actually constrains the price. */
    posRetailHasPriceRange(productTemplate) {
        const minimum = productTemplate?.minimum_selling_price || 0;
        const maximum = productTemplate?.mrp || 0;
        return Boolean(minimum || maximum) && minimum !== maximum;
    },

    async posRetailAskPriceReason() {
        const reasons = this.models["pos.retail.price.reason"].getAll();
        if (!reasons.length) {
            return null;
        }
        return makeAwaitable(this.dialog, SelectionPopup, {
            title: _t("Reason for the price override"),
            list: reasons.map((reason) => ({
                id: reason.id,
                label: reason.name,
                isSelected: false,
                item: reason,
            })),
        });
    },

    async addLineToCurrentOrder(vals, opts = {}, configure = true) {
        const productTemplate = vals.product_tmpl_id;
        const shouldAsk =
            configure !== false &&
            this.config.pos_retail_price_range_enabled &&
            !("price_unit" in vals) &&
            this.posRetailHasPriceRange(productTemplate);

        if (!shouldAsk) {
            return await super.addLineToCurrentOrder(vals, opts, configure);
        }

        const payload = await makeAwaitable(this.dialog, PriceSelectionPopup, {
            product: productTemplate,
        });
        if (!payload) {
            // Cancelled: add nothing rather than silently falling back to the
            // default price, which the cashier may not have intended.
            return;
        }

        let manager = false;
        let reason = false;
        if (payload.isOutOfRange) {
            manager = await posRetailRequestManagerPin(this, this.dialog, this.notification, {
                noManagerMessage: _t("No manager is configured to approve price changes."),
            });
            if (!manager) {
                return;
            }
            if (this.config.pos_retail_price_override_requires_reason) {
                reason = await this.posRetailAskPriceReason();
                if (reason === false) {
                    return;
                }
            }
        }

        // Supplying price_unit is what makes core mark the line "manual", skip
        // the pricelist lookup and keep it out of any merge, so the chosen
        // price survives later pricelist/quantity changes.
        vals.price_unit = payload.price;
        const line = await super.addLineToCurrentOrder(vals, opts, configure);

        if (line) {
            line.pos_retail_default_price = productTemplate.list_price || 0;
            line.pos_retail_min_price = productTemplate.minimum_selling_price || 0;
            line.pos_retail_max_price = productTemplate.mrp || 0;
            line.pos_retail_price_state = payload.isOutOfRange
                ? "overridden"
                : payload.isDefault
                ? "default"
                : "adjusted";
            line.pos_retail_price_manager_id = manager || false;
            line.pos_retail_price_reason_id = reason || false;
        }
        return line;
    },
});

// Colour the cart line by how its price was set. getDisplayClasses is core's
// purpose-built extension point for this (it returns {} in core) and its result
// is merged into the orderline's container classes.
patch(PosOrderline.prototype, {
    getDisplayClasses() {
        return {
            ...super.getDisplayClasses(),
            "pos-retail-line-adjusted": this.pos_retail_price_state === "adjusted",
            "pos-retail-line-overridden": this.pos_retail_price_state === "overridden",
        };
    },
});

// Editing the price of a line already in the cart (numpad "Price" mode) runs
// through the same range rules, so a price cannot be walked out of range after
// the fact to dodge the popup.
patch(OrderSummary.prototype, {
    async setLinePrice(line, price) {
        const product = line.product_id?.product_tmpl_id;
        const minimum = line.pos_retail_min_price || product?.minimum_selling_price || 0;
        const maximum = line.pos_retail_max_price || product?.mrp || 0;
        const newPrice = typeof price === "number" ? price : parseFloat(price);
        const outOfRange =
            Number.isFinite(newPrice) &&
            ((minimum && newPrice < minimum) || (maximum && newPrice > maximum));

        if (!this.pos.config.pos_retail_price_range_enabled || !outOfRange) {
            await super.setLinePrice(line, price);
            if (Number.isFinite(newPrice) && (minimum || maximum)) {
                const isDefault = newPrice === (product?.list_price || 0);
                line.pos_retail_price_state = isDefault ? "default" : "adjusted";
            }
            return;
        }

        // OrderSummary itself only injects number_buffer/dialog/pos, so the
        // notification service is reached through the store.
        const notification = this.pos.notification;
        notification.add(
            newPrice < minimum
                ? _t("The entered price is below the minimum selling price.")
                : _t("The entered price exceeds the maximum selling price."),
            { type: "warning" }
        );
        const manager = await posRetailRequestManagerPin(
            this.pos,
            this.dialog,
            notification,
            { noManagerMessage: _t("No manager is configured to approve price changes.") }
        );
        if (!manager) {
            return;
        }
        let reason = false;
        if (this.pos.config.pos_retail_price_override_requires_reason) {
            reason = await this.pos.posRetailAskPriceReason();
            if (reason === false) {
                return;
            }
        }

        await super.setLinePrice(line, price);
        line.pos_retail_min_price = minimum;
        line.pos_retail_max_price = maximum;
        line.pos_retail_default_price = product?.list_price || 0;
        line.pos_retail_price_state = "overridden";
        line.pos_retail_price_manager_id = manager;
        line.pos_retail_price_reason_id = reason || false;
    },
});
