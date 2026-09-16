/** @odoo-module **/

import { patch } from "@web/core/utils/patch";
import { _t } from "@web/core/l10n/translation";
import { PaymentScreen } from "@point_of_sale/app/screens/payment_screen/payment_screen";
import { PosStore } from "@point_of_sale/app/services/pos_store";
import { Chrome } from "@point_of_sale/app/pos_app";

// Defensive guard: never allow closeOtherTabs or connectToProxy to crash or hang POS startup
patch(PosStore.prototype, {
    closeOtherTabs() {
        if (!this.session || !this.session.id) {
            return;
        }
        try {
            return super.closeOtherTabs(...arguments);
        } catch (_) {}
    },

    async connectToProxy() {
        const proxyIp = this.config?.proxy_ip || "";
        const storedUrl = typeof localStorage !== "undefined" ? localStorage.hw_proxy_url : "";
        if (!proxyIp && !storedUrl) {
            return;
        }
        try {
            // Core autoConnect returns an unresolving pending promise if no URL exists,
            // or hangs on network timeouts. Race with 2s timeout so POS startup never hangs.
            await Promise.race([
                super.connectToProxy(...arguments),
                new Promise((resolve) => setTimeout(resolve, 2000)),
            ]);
        } catch (_) {}
    },
});

// Guard Chrome root component: ensure the 3-dots loader is dismissed promptly after mount
patch(Chrome.prototype, {
    setup() {
        super.setup(...arguments);
        setTimeout(() => {
            try {
                this.props?.disableLoader?.();
            } catch (_) {}
            const loaderEl = document.querySelector(".pos-loader");
            if (loaderEl) {
                loaderEl.style.transition = "opacity 0.3s ease";
                loaderEl.style.opacity = "0";
                setTimeout(() => {
                    try {
                        loaderEl.remove();
                    } catch (_) {}
                }, 350);
            }
        }, 1800);
    },
});

// Global emergency watchdog: if the loader element remains visible after 4.5 seconds, remove it
if (typeof window !== "undefined") {
    setTimeout(() => {
        const loaderEl = document.querySelector(".pos-loader");
        if (loaderEl) {
            loaderEl.style.transition = "opacity 0.3s ease";
            loaderEl.style.opacity = "0";
            setTimeout(() => {
                try {
                    loaderEl.remove();
                } catch (_) {}
            }, 350);
        }
    }, 4500);
}

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
