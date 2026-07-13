/** @odoo-module **/

import { patch } from "@web/core/utils/patch";
import { _t } from "@web/core/l10n/translation";
import { PaymentScreen } from "@point_of_sale/app/screens/payment_screen/payment_screen";

// Live, best-effort warning only — never blocks the sale. `qty_available` is a
// snapshot pulled at session-load time (see product_product.py's
// `_load_pos_data_fields` override), not live-pushed, so under concurrent
// multi-terminal sales it can be stale in either direction during a session.
// That's inherent to POS's offline-first cached architecture, not a bug.
patch(PaymentScreen.prototype, {
    async validateOrder(isForceValidate) {
        this._posRetailWarnNegativeStock();
        return super.validateOrder(isForceValidate);
    },

    _posRetailWarnNegativeStock() {
        try {
            const qtyByProduct = new Map();
            for (const line of this.currentOrder.lines) {
                const product = line.getProduct();
                if (!product?.product_tmpl_id?.is_storable) {
                    continue;
                }
                const entry = qtyByProduct.get(product.id) || { product, qty: 0 };
                entry.qty += line.getQuantity();
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
