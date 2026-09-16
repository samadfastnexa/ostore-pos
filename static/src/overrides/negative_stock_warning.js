/** @odoo-module **/

import { patch } from "@web/core/utils/patch";
import { _t } from "@web/core/l10n/translation";
import { PaymentScreen } from "@point_of_sale/app/screens/payment_screen/payment_screen";
import OrderPaymentValidation from "@point_of_sale/app/utils/order_payment_validation";

function _posRetailExtractOrderLines(order) {
    const linesData = [];
    if (order && order.lines) {
        for (const line of order.lines) {
            const product = line.getProduct ? line.getProduct() : line.product_id;
            const qty = typeof line.getQuantity === "function" ? line.getQuantity() : (line.qty || 0);
            if (product && qty) {
                linesData.push({ product, qty });
            }
        }
    }
    return linesData;
}

function _posRetailApplyStockDeductions(pos, linesData) {
    if (!linesData || !linesData.length) {
        return;
    }

    const productIdsToRefresh = new Set();

    for (const { product, qty } of linesData) {
        if (!product || !qty) {
            continue;
        }
        const isStorable = product.product_tmpl_id?.is_storable ?? product.is_storable;
        if (!isStorable) {
            continue;
        }

        // 1. Immediately decrement in reactive memory for instant UI update on till product cards
        if (typeof product.qty_available === "number") {
            product.qty_available -= qty;
        }

        if (product.product_tmpl_id && typeof product.product_tmpl_id.qty_available === "number") {
            product.product_tmpl_id.qty_available -= qty;
        }

        if (product.id) {
            productIdsToRefresh.add(product.id);
        }
    }

    // 2. Refresh authoritative stock from backend database in the background
    if (productIdsToRefresh.size > 0 && pos?.data?.read) {
        pos.data.read("product.product", Array.from(productIdsToRefresh), ["qty_available"])
            .catch(() => {
                // Non-blocking: network drop or offline mode will not break POS checkout
            });
    }
}

// Order validation pipeline hook (covers normal checkout and fast payment)
patch(OrderPaymentValidation.prototype, {
    async finalizeValidation() {
        const order = this.order;
        const linesData = _posRetailExtractOrderLines(order);

        const result = await super.finalizeValidation(...arguments);

        if (order && !order._posRetailStockUpdated && order.state !== "draft") {
            order._posRetailStockUpdated = true;
            _posRetailApplyStockDeductions(this.pos, linesData);
        }

        return result;
    },
});

// Live, best-effort warning before sale, plus fallback trigger after checkout
patch(PaymentScreen.prototype, {
    async validateOrder(isForceValidate) {
        this._posRetailWarnNegativeStock();
        const order = this.currentOrder;
        const linesData = _posRetailExtractOrderLines(order);

        const result = await super.validateOrder(...arguments);

        if (order && !order._posRetailStockUpdated && order.state !== "draft") {
            order._posRetailStockUpdated = true;
            _posRetailApplyStockDeductions(this.pos, linesData);
        }

        return result;
    },

    _posRetailWarnNegativeStock() {
        try {
            const qtyByProduct = new Map();
            for (const line of this.currentOrder.lines) {
                const product = line.getProduct ? line.getProduct() : line.product_id;
                const isStorable = product?.product_tmpl_id?.is_storable ?? product?.is_storable;
                if (!isStorable) {
                    continue;
                }
                const entry = qtyByProduct.get(product.id) || { product, qty: 0 };
                const lineQty = typeof line.getQuantity === "function" ? line.getQuantity() : (line.qty || 0);
                entry.qty += lineQty;
                qtyByProduct.set(product.id, entry);
            }

            const shortages = [];
            for (const { product, qty } of qtyByProduct.values()) {
                const available = product.qty_available;
                if (qty > 0 && typeof available === "number" && qty > available) {
                    shortages.push(product.display_name);
                }
            }

            if (shortages.length) {
                this.notification.add(
                    _t("Low stock: selling more than on hand for %s", shortages.join(", ")),
                    { type: "warning" }
                );
            }
        } catch {
            // Best-effort UI warning only -- never let this block checkout.
        }
    },
});
