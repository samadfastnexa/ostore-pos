/** @odoo-module **/

import { patch } from "@web/core/utils/patch";
import { _t } from "@web/core/l10n/translation";
import { Orderline } from "@point_of_sale/app/components/orderline/orderline";
import { OrderSummary } from "@point_of_sale/app/screens/product_screen/order_summary/order_summary";
import { PosStore } from "@point_of_sale/app/services/pos_store";
import { makeAwaitable } from "@point_of_sale/app/utils/make_awaitable_dialog";
import { LineDiscountPopup } from "./line_discount_popup";
import { PriceSelectionPopup } from "./price_popup";
import { posRetailRequestManagerPin } from "../utils/manager_pin";

// Register onDiscount callback prop on Orderline
Orderline.props = {
    ...Orderline.props,
    onDiscount: { type: Function, optional: true },
    onSetPrice: { type: Function, optional: true },
};

// Add helper for formatted discount amount display on Orderline
patch(Orderline.prototype, {
    posRetailDiscountAmount(line) {
        const targetLine = line || this.line;
        if (!targetLine) {
            return "";
        }
        const unitPrice = targetLine.price_unit || 0;
        const discountPct = targetLine.discount || 0;
        const totalDiscount = (unitPrice * discountPct / 100) * (targetLine.qty || 1);
        if (this.env?.utils?.formatCurrency) {
            return this.env.utils.formatCurrency(totalDiscount);
        }
        return totalDiscount.toFixed(2);
    },
});

// Patch OrderSummary to open LineDiscountPopup when cashier clicks discount button
patch(OrderSummary.prototype, {
    async posRetailOpenLineDiscount(line) {
        if (!line || line.qty <= 0 || line.refunded_orderline_id || line.isGlobalDiscountLine?.()) {
            return;
        }
        if (!this.pos.config.pos_retail_line_discount_enabled) {
            return;
        }
        await makeAwaitable(this.dialog, LineDiscountPopup, { line });
    },

    /**
     * A direct, labelled price action is easier to discover than switching
     * the keypad to Price mode.  It reuses the same range-aware popup used
     * when a ranged product is first added, then delegates to setLinePrice so
     * the existing manager-PIN and minimum/maximum checks still apply.
     */
    async posRetailOpenLinePrice(line) {
        if (!line || line.qty <= 0 || line.refunded_orderline_id || line.isGlobalDiscountLine?.()) {
            return;
        }
        const product = line.product_id?.product_tmpl_id;
        if (!product) {
            return;
        }
        const payload = await makeAwaitable(this.dialog, PriceSelectionPopup, {
            product,
            initialPrice: line.price_unit || 0,
        });
        if (!payload) {
            return;
        }
        await this.setLinePrice(line, payload.price);
    },
});

// Intercept numpad discount entry (setDiscountFromUI) to enforce Minimum Selling Price
patch(PosStore.prototype, {
    async setDiscountFromUI(line, val) {
        if (!line || line.isGlobalDiscountLine?.()) {
            return await super.setDiscountFromUI(line, val);
        }

        const discountNum = typeof val === "number" ? val : parseFloat(val);
        if (!Number.isFinite(discountNum) || discountNum <= 0) {
            line.pos_retail_line_discount_manager_id = false;
            return await super.setDiscountFromUI(line, val);
        }

        const minPrice = line.pos_retail_min_price || line.product_id?.product_tmpl_id?.minimum_selling_price || 0;
        const unitPrice = line.price_unit || 0;
        const finalPrice = unitPrice * (1 - discountNum / 100);

        if (minPrice > 0 && finalPrice < minPrice - 0.001) {
            const format = this.env?.utils?.formatCurrency || ((v) => String(v));
            const formattedMin = format(minPrice);
            const formattedFinal = format(finalPrice);

            if (!this.config.pos_retail_line_discount_manager_below_min) {
                this.notification.add(
                    _t(
                        "⚠️ Discount not allowed: price (%s) would fall below minimum allowed price (%s).",
                        formattedFinal,
                        formattedMin
                    ),
                    { type: "danger" }
                );
                return;
            }

            this.notification.add(
                _t(
                    "Discount reduces price below minimum (%s). Manager approval required.",
                    formattedMin
                ),
                { type: "warning" }
            );

            const manager = await posRetailRequestManagerPin(this, this.dialog, this.notification, {
                title: _t("Manager PIN — Below Minimum Discount"),
                noManagerMessage: _t("No manager is configured to approve discounts below minimum price."),
            });

            if (!manager) {
                return;
            }

            line.pos_retail_line_discount_manager_id = manager;
            line.pos_retail_line_discount_input_type = "percent";
        } else {
            line.pos_retail_line_discount_manager_id = false;
            line.pos_retail_line_discount_input_type = "percent";
        }

        return await super.setDiscountFromUI(line, val);
    },

    /**
     * Requirement 9: Brand campaigns / promotions must also respect minimum selling price.
     * Cap promotion discount so selling price does not fall below minimum_selling_price.
     */
    posRetailUnitDiscount(promo, unitPrice, tmplId) {
        const rawDiscount = super.posRetailUnitDiscount
            ? super.posRetailUnitDiscount(...arguments)
            : (promo?.discount_value || 0);

        if (!tmplId || !rawDiscount) {
            return rawDiscount;
        }

        const template = this.models["product.template"]?.get(tmplId);
        const minPrice = template?.minimum_selling_price || 0;
        if (minPrice > 0 && unitPrice > minPrice) {
            const maxAllowedPromoDiscount = Math.max(0, unitPrice - minPrice);
            return Math.min(rawDiscount, maxAllowedPromoDiscount);
        }
        return rawDiscount;
    },
});
