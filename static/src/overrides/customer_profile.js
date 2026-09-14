/** @odoo-module **/

import { _t } from "@web/core/l10n/translation";
import { Component, onWillStart, useState } from "@odoo/owl";
import { Dialog } from "@web/core/dialog/dialog";
import { usePos } from "@point_of_sale/app/hooks/pos_hook";
import { useService } from "@web/core/utils/hooks";
import { makeAwaitable } from "@point_of_sale/app/utils/make_awaitable_dialog";
import { AlertDialog } from "@web/core/confirmation_dialog/confirmation_dialog";
import { PartnerList } from "@point_of_sale/app/screens/partner_list/partner_list";
import { ReceivePaymentPopup } from "./receive_payment_popup";
import { PaymentReceiptPopup } from "./payment_receipt_popup";


// Unified Customer & Vendor Profile + Ledger + Transaction History for POS Cashiers.
// Supports in-modal switching between any customer or vendor without leaving the dialog.
export class PosRetailCustomerProfile extends Component {
    static template = "pos_retail.CustomerProfile";
    static components = { Dialog };
    static props = {
        partner: Object,
        close: Function,
    };

    setup() {
        this.pos = usePos();
        this.dialog = useService("dialog");
        this.notification = useService("notification");
        this.state = useState({
            currentPartner: this.props.partner,
            showSwitcher: false,
            searchQuery: "",
            filterType: "all", // "all", "customer", "vendor"
            activeSide: "customer", // "customer" or "vendor"
            customerTab: "sales",   // "sales", "payments", "open", "purchases", "credit", "refunds", "quotations"
            vendorTab: "purchase_orders", // "purchase_orders", "vendor_bills", "vendor_payments", "unpaid_bills"
            loading: true,
            failed: false,
            data: null,
            searchingServer: false,
            serverResults: [],
        });

        onWillStart(async () => {
            await this.loadPartnerData(this.state.currentPartner);
        });
    }

    get partner() {
        return this.state.currentPartner;
    }

    get tags() {
        return this.partner.category_id || [];
    }

    get isCurrentOrderPartner() {
        const orderPartner = this.pos.getOrder()?.getPartner();
        return Boolean(orderPartner && orderPartner.id === this.partner?.id);
    }

    async loadPartnerData(partner) {
        if (!partner) return;
        this.state.currentPartner = partner;
        this.state.loading = true;
        this.state.failed = false;
        this.state.showSwitcher = false;
        this.state.searchQuery = "";
        this.state.serverResults = [];
        try {
            const data = await this.pos.data.call(
                "res.partner",
                "get_pos_customer_history",
                [[partner.id]]
            );
            this.state.data = data;
            // If partner is purely a supplier with no retail sales, default to vendor side
            if (data.is_vendor && !data.sales_count && (data.purchase_orders_count || data.vendor_bills?.length)) {
                this.state.activeSide = "vendor";
            } else {
                this.state.activeSide = "customer";
            }
        } catch (err) {
            console.warn("PosRetail: Failed to fetch online history for partner:", err);
            this.state.failed = true;
        } finally {
            this.state.loading = false;
        }
    }

    toggleSwitcher() {
        this.state.showSwitcher = !this.state.showSwitcher;
        this.state.searchQuery = "";
        this.state.serverResults = [];
    }

    setFilterType(type) {
        this.state.filterType = type;
    }

    get matchingPartners() {
        const query = (this.state.searchQuery || "").trim().toLowerCase();
        const type = this.state.filterType;
        let allLocal = [];
        try {
            const partnerModel = this.pos.models["res.partner"];
            if (partnerModel) {
                if (typeof partnerModel.getAll === "function") {
                    allLocal = partnerModel.getAll();
                } else if (Array.isArray(partnerModel)) {
                    allLocal = partnerModel;
                } else if (typeof partnerModel[Symbol.iterator] === "function") {
                    allLocal = Array.from(partnerModel);
                } else if (partnerModel.records) {
                    allLocal = partnerModel.records;
                }
            }
        } catch (e) {
            allLocal = [];
        }
        const serverResults = this.state.serverResults || [];

        // Combine local and server results avoiding duplicate IDs
        const seenIds = new Set();
        const combined = [];
        for (const p of [...serverResults, ...allLocal]) {
            if (!p || !p.id || seenIds.has(p.id)) continue;
            seenIds.add(p.id);
            combined.push(p);
        }

        const filtered = combined.filter((p) => {
            if (type === "customer") {
                if (p.supplier_rank > 0 && !p.customer_rank && !p.pos_sales_order_count) {
                    return false;
                }
            } else if (type === "vendor") {
                if (!p.supplier_rank && !(p.supplier_rank > 0)) {
                    return false;
                }
            }
            if (!query) {
                return true;
            }
            const name = (p.name || "").toLowerCase();
            const phone = (p.phone || "").toLowerCase();
            const mobile = (p.mobile || "").toLowerCase();
            const email = (p.email || "").toLowerCase();
            const ref = (p.ref || "").toLowerCase();
            return (
                name.includes(query) ||
                phone.includes(query) ||
                mobile.includes(query) ||
                email.includes(query) ||
                ref.includes(query)
            );
        });

        return filtered.slice(0, 30);
    }

    async onSearchKeydown(ev) {
        if (ev.key === "Enter") {
            ev.preventDefault();
            const matches = this.matchingPartners;
            if (matches.length === 1) {
                await this.selectPartner(matches[0]);
            } else if (matches.length === 0 && this.state.searchQuery.trim()) {
                await this.searchServerPartners();
            }
        }
    }

    async selectPartner(partner) {
        await this.loadPartnerData(partner);
    }

    async browseAllPartners() {
        try {
            const payload = await makeAwaitable(this.dialog, PartnerList, {
                partner: this.partner,
            });
            if (payload && payload.id) {
                await this.loadPartnerData(payload);
            }
        } catch (err) {
            console.warn("PosRetail: browse partner error", err);
        }
    }

    async searchServerPartners() {
        const query = (this.state.searchQuery || "").trim();
        if (!query) return;
        this.state.searchingServer = true;
        try {
            const domain = [
                "|", "|", "|",
                ["name", "ilike", query],
                ["phone", "ilike", query],
                ["mobile", "ilike", query],
                ["email", "ilike", query],
            ];
            const records = await this.pos.data.call(
                "res.partner",
                "search_read",
                [domain, ["id", "name", "phone", "mobile", "email", "pos_contact_address", "supplier_rank", "customer_rank", "pos_outstanding_balance"]],
                { limit: 25 }
            );
            this.state.serverResults = records || [];
            if (records && records.length) {
                this.notification.add(
                    _t("%s partner(s) found on server.", records.length),
                    { type: "info" }
                );
            } else {
                this.notification.add(
                    _t("No partners found on server for '%s'.", query),
                    { type: "warning" }
                );
            }
        } catch (err) {
            console.warn("PosRetail: server partner search failed", err);
        } finally {
            this.state.searchingServer = false;
        }
    }

    setAsCurrentOrderCustomer() {
        const order = this.pos.getOrder();
        if (order) {
            this.pos.setPartnerToCurrentOrder(this.partner);
            this.notification.add(
                _t("%s set as active customer on current order.", this.partner.name),
                { type: "success" }
            );
        }
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

    /** Receive customer khata/credit payment directly within the profile/ledger dialog. */
    async onClickReceivePayment() {
        const partner = this.partner;
        if (!partner) {
            return;
        }

        const paymentResult = await makeAwaitable(this.dialog, ReceivePaymentPopup, {
            partner,
        });

        if (!paymentResult) {
            return;
        }

        // Show success notification
        this.notification.add(
            _t(
                "%(paid)s received from %(name)s. Net balance owed: %(balance)s.",
                {
                    paid: paymentResult.paid_formatted || this.formatCurrency(paymentResult.paid),
                    name: partner.name,
                    balance: paymentResult.new_balance_formatted || this.formatCurrency(paymentResult.new_balance),
                }
            ),
            { type: "success" }
        );

        // Open Printable Payment Receipt modal immediately
        await makeAwaitable(this.dialog, PaymentReceiptPopup, {
            receipt: paymentResult,
        });

        // Reactively reload partner ledger and history immediately!
        await this.loadPartnerData(partner);
    }
}

