/** @odoo-module **/

import { _t } from "@web/core/l10n/translation";
import { Component, onWillStart, useState } from "@odoo/owl";
import { Dialog } from "@web/core/dialog/dialog";
import { usePos } from "@point_of_sale/app/hooks/pos_hook";
import { useService } from "@web/core/utils/hooks";

// Unified Customer & Vendor Profile + Ledger + Transaction History for POS Cashiers.
// Combines customer profile, debit/credit accounting summaries, and vendor history
// in a single popup with side-by-side tabs on the cashier screen.
export class PosRetailCustomerProfile extends Component {
    static template = "pos_retail.CustomerProfile";
    static components = { Dialog };
    static props = {
        partner: Object,
        close: Function,
    };

    setup() {
        this.pos = usePos();
        this.notification = useService("notification");
        this.state = useState({
            activeSide: "customer", // "customer" or "vendor"
            customerTab: "sales",   // "sales", "payments", "open", "purchases", "credit", "refunds", "quotations"
            vendorTab: "purchase_orders", // "purchase_orders", "vendor_bills", "vendor_payments", "unpaid_bills"
            loading: true,
            failed: false,
            data: null,
        });

        onWillStart(async () => {
            try {
                const data = await this.pos.data.call(
                    "res.partner",
                    "get_pos_customer_history",
                    [[this.props.partner.id]]
                );
                this.state.data = data;
                // If partner is purely a supplier with no retail sales, default to vendor side
                if (data.is_vendor && !data.sales_count && (data.purchase_orders_count || data.vendor_bills?.length)) {
                    this.state.activeSide = "vendor";
                }
            } catch (err) {
                console.warn("PosRetail: Failed to fetch online history for partner:", err);
                this.state.failed = true;
            } finally {
                this.state.loading = false;
            }
        });
    }

    get partner() {
        return this.props.partner;
    }

    get tags() {
        return this.partner.category_id || [];
    }

    setActiveSide(side) {
        this.state.activeSide = side;
    }

    setCustomerTab(tab) {
        this.state.customerTab = tab;
    }

    setVendorTab(tab) {
        this.state.vendorTab = tab;
    }

    formatCurrency(value) {
        return this.pos.env.utils.formatCurrency(value || 0);
    }

    get lastPurchase() {
        const raw = this.state.data?.last_purchase_date || this.partner.pos_last_purchase_date;
        if (!raw) {
            return _t("Never");
        }
        const then = typeof raw === "string" ? new Date(raw.replace(" ", "T") + "Z") : raw.toJSDate?.() ?? new Date(raw);
        const days = Math.floor((Date.now() - then.getTime()) / 86400000);
        if (days <= 0) {
            return _t("Today");
        }
        if (days === 1) {
            return _t("Yesterday");
        }
        if (days < 30) {
            return _t("%s days ago", days);
        }
        const months = Math.floor(days / 30);
        return months === 1 ? _t("A month ago") : _t("%s months ago", months);
    }

    get hasCreditLimit() {
        return Boolean(this.partner.pos_credit_limit || this.state.data?.credit_limit);
    }

    get overLimit() {
        const avail = this.state.data ? this.state.data.credit_available : this.partner.pos_credit_available;
        return this.hasCreditLimit && avail < 0;
    }

    /** One-tap repeat of the customer's last order into the current POS cart. */
    async repeatLastOrder() {
        const basket = this.state.data?.last_basket || [];
        if (!basket.length) {
            this.notification.add(_t("This customer has no previous order to repeat."), {
                type: "warning",
            });
            return;
        }
        let added = 0;
        const skipped = [];
        for (const item of basket) {
            const product = this.pos.models["product.product"].get(item.product_id);
            if (!product) {
                skipped.push(item.name);
                continue;
            }
            await this.pos.addLineToCurrentOrder(
                { product_id: product, product_tmpl_id: product.product_tmpl_id, qty: item.qty },
                {}
            );
            added += 1;
        }
        if (added) {
            this.notification.add(
                _t("%s product(s) added to cart at today's prices.", added),
                { type: "success" }
            );
        }
        if (skipped.length) {
            this.notification.add(
                _t("Not available any more: %s", skipped.join(", ")),
                { type: "warning" }
            );
        }
        this.props.close();
    }
}
