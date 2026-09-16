/** @odoo-module **/

import { patch } from "@web/core/utils/patch";
import { _t } from "@web/core/l10n/translation";
import { PaymentScreen } from "@point_of_sale/app/screens/payment_screen/payment_screen";
import { PosStore } from "@point_of_sale/app/services/pos_store";
import { Chrome } from "@point_of_sale/app/pos_app";

// Install global error listeners so unhandled errors or promise rejections are never silent
if (typeof window !== "undefined" && !window._posRetailDiagInstalled) {
    window._posRetailDiagInstalled = true;
    window.addEventListener("unhandledrejection", (ev) => {
        console.error("[POS-DIAG] Unhandled Promise Rejection:", ev.reason);
    });
    window.addEventListener("error", (ev) => {
        console.error("[POS-DIAG] Unhandled Window Error:", ev.error || ev.message, ev.filename, ev.lineno);
    });
    console.log("%c[POS-DIAG] pos_retail diagnostic monitoring active", "background: #222; color: #00ffcc; font-weight: bold; padding: 2px 6px;");
}

// Defensive guard & diagnostics on PosStore startup lifecycle
patch(PosStore.prototype, {
    async setup() {
        console.log("%c[POS-DIAG] PosStore.setup() STARTING", "color: #00b4d8; font-weight: bold;", {
            pos_config_id: odoo?.pos_config_id,
            pos_session_id: odoo?.pos_session_id,
            from_backend: odoo?.from_backend,
        });
        try {
            const res = await super.setup(...arguments);
            console.log("%c[POS-DIAG] PosStore.setup() FINISHED", "color: #52b788; font-weight: bold;", {
                session: this.session ? { id: this.session.id, state: this.session.state } : "NONE",
                config: this.config ? { id: this.config.id, name: this.config.name, useProxy: this.config.useProxy } : "NONE",
                activeRoute: this.router?.state?.current,
            });
            return res;
        } catch (err) {
            console.error("%c[POS-DIAG] PosStore.setup() FAILED WITH ERROR:", "color: #e63946; font-weight: bold;", err);
            throw err;
        }
    },


    async connectToProxy() {
        const proxyIp = this.config?.proxy_ip || "";
        const storedUrl = typeof localStorage !== "undefined" ? localStorage.hw_proxy_url : "";
        console.log("[POS-DIAG] PosStore.connectToProxy() called", {
            proxyIp,
            storedUrl,
            useProxy: this.config?.useProxy,
        });
        if (!proxyIp && !storedUrl) {
            console.warn("[POS-DIAG] Skipping connectToProxy to avoid hanging dead promise (no proxy IP configured)");
            return;
        }
        try {
            console.log("[POS-DIAG] Attempting connectToProxy with 2s timeout guard...");
            await Promise.race([
                super.connectToProxy(...arguments),
                new Promise((resolve) => setTimeout(resolve, 2000)),
            ]);
            console.log("[POS-DIAG] connectToProxy completed or timed out cleanly");
        } catch (err) {
            console.warn("[POS-DIAG] connectToProxy error caught safely:", err);
        }
    },
});

// Guard Chrome root component: ensure the 3-dots loader is dismissed promptly after mount
patch(Chrome.prototype, {
    setup() {
        console.log("%c[POS-DIAG] Chrome root component setup() RUNNING", "background: #005577; color: #fff; padding: 2px 6px;", {
            currentRoute: this.pos?.router?.state?.current,
            session: this.pos?.session ? { id: this.pos.session.id, state: this.pos.session.state } : "NONE",
        });
        super.setup(...arguments);
        setTimeout(() => {
            console.log("[POS-DIAG] Chrome watchdog fired at 1.8s. Checking loader overlay...");
            try {
                this.props?.disableLoader?.();
            } catch (err) {
                console.warn("[POS-DIAG] disableLoader error:", err);
            }
            const loaderEl = document.querySelector(".pos-loader");
            if (loaderEl) {
                console.log("[POS-DIAG] Dismissing .pos-loader element from DOM");
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
            console.warn("[POS-DIAG] Emergency watchdog at 4.5s: removing stuck loader element");
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
