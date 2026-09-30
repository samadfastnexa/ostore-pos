/** @odoo-module **/

import { Component, onWillStart, useState } from "@odoo/owl";
import { Dialog } from "@web/core/dialog/dialog";
import { _t } from "@web/core/l10n/translation";
import { usePos } from "@point_of_sale/app/hooks/pos_hook";
import { useService } from "@web/core/utils/hooks";
import { PosRetailVendorPaymentPopup } from "./vendor_payment_popup";
import { PosRetailVendorAdjustPopup } from "./vendor_adjust_popup";
import { PosRetailCustomerProfile } from "./customer_profile";
import { openWhatsAppChoice } from "../backend/whatsapp_choice_dialog";

export class PosRetailVendorModal extends Component {
    static template = "pos_retail.VendorModal";
    static components = { Dialog };
    static props = {
        close: Function,
    };

    setup() {
        this.pos = usePos();
        this.dialog = useService("dialog");
        this.notification = useService("notification");

        this.state = useState({
            loading: true,
            searchQuery: "",
            filter: "all", // "all", "owed", "settled"
            vendors: [],
            totalVendors: 0,
            totalPayable: 0,
            totalPayableFormatted: "0.00 Rs.",
            currencySymbol: "Rs.",
            showAddForm: false,
            newVendor: {
                name: "",
                vendor_contact_person: "",
                phone: "",
                mobile: "",
                email: "",
                city: "",
                opening_balance: "",
                notes: "",
            },
            isSaving: false,
            errorMessage: "",
        });

        this._searchTimeout = null;

        onWillStart(async () => {
            await this.fetchVendors("");
        });
    }

    async fetchVendors(query = "") {
        this.state.loading = true;
        this.state.errorMessage = "";
        try {
            const res = await this.pos.data.call(
                "res.partner",
                "pos_retail_search_vendors",
                [query, this.pos.config.id, 100]
            );
            this.state.vendors = res.vendors || [];
            this.state.totalVendors = res.total_vendors || 0;
            this.state.totalPayable = res.total_payable || 0;
            this.state.totalPayableFormatted = res.total_payable_formatted || "0.00 Rs.";
            this.state.currencySymbol = res.currency_symbol || "Rs.";
        } catch (err) {
            this.state.errorMessage =
                err?.data?.message || err?.message || _t("Failed to load vendors.");
        } finally {
            this.state.loading = false;
        }
    }

    onSearchInput(ev) {
        const query = ev.target.value;
        this.state.searchQuery = query;
        clearTimeout(this._searchTimeout);
        this._searchTimeout = setTimeout(() => {
            this.fetchVendors(query);
        }, 300);
    }

    clearSearch() {
        this.state.searchQuery = "";
        this.fetchVendors("");
    }

    setFilter(filter) {
        this.state.filter = filter;
    }

    get filteredVendors() {
        const list = this.state.vendors || [];
        if (this.state.filter === "owed") {
            return list.filter((v) => (v.balance || 0) > 0);
        }
        if (this.state.filter === "settled") {
            return list.filter((v) => (v.balance || 0) <= 0);
        }
        return list;
    }

    toggleAddForm() {
        this.state.showAddForm = !this.state.showAddForm;
        this.state.errorMessage = "";
        if (this.state.showAddForm) {
            this.state.newVendor = {
                name: "",
                vendor_contact_person: "",
                phone: "",
                mobile: "",
                email: "",
                city: "",
                opening_balance: "",
                notes: "",
            };
        }
    }

    async saveNewVendor() {
        const vals = this.state.newVendor;
        if (!vals.name || !vals.name.trim()) {
            this.state.errorMessage = _t("Please enter a vendor business name.");
            return;
        }

        this.state.isSaving = true;
        this.state.errorMessage = "";
        try {
            const cashier = this.pos.getCashier();
            const created = await this.pos.data.call(
                "res.partner",
                "pos_retail_create_vendor",
                [vals, this.pos.config.id, cashier?.id || false]
            );

            this.notification.add(
                _t("Vendor %(name)s added successfully!", { name: created.name }),
                { type: "success" }
            );

            this.state.showAddForm = false;
            // Prepend new vendor to list
            this.state.vendors.unshift(created);
            this.state.totalVendors += 1;
            if (created.balance > 0) {
                this.state.totalPayable += created.balance;
            }
        } catch (err) {
            this.state.errorMessage =
                err?.data?.message || err?.message || _t("Failed to create vendor.");
        } finally {
            this.state.isSaving = false;
        }
    }

    onClickPayVendor(vendor) {
        this.dialog.add(PosRetailVendorPaymentPopup, {
            vendor,
            onPaymentDone: () => {
                this.fetchVendors(this.state.searchQuery);
            },
        });
    }

    onClickAdjustKhata(vendor) {
        this.dialog.add(PosRetailVendorAdjustPopup, {
            vendor,
            onAdjustDone: () => {
                this.fetchVendors(this.state.searchQuery);
            },
        });
    }

    onClickStatement(vendor) {
        this.dialog.add(PosRetailCustomerProfile, {
            partner: { id: vendor.id, name: vendor.name },
        });
    }

    async onClickShareWhatsApp(vendor) {
        const phone = vendor.contact_phone || vendor.mobile || vendor.phone || "";
        const shopName = this.pos.company?.name || "Retail Store";
        const today = new Date().toLocaleDateString();

        const lines = [
            `*${shopName}*`,
            `*VENDOR ACCOUNT & KHATA SUMMARY*`,
            `Date: ${today}`,
            `--------------------------------`,
            `*Vendor:* ${vendor.name}`,
        ];
        if (vendor.vendor_contact_person) {
            lines.push(`*Attn:* ${vendor.vendor_contact_person}`);
        }
        if (phone) {
            lines.push(`*Phone:* ${phone}`);
        }
        lines.push(``);
        lines.push(`*Total Invoiced / Bills:* ${vendor.bills_total_formatted}`);
        lines.push(`*Total Payments Made:* ${vendor.paid_total_formatted}`);
        lines.push(`*CURRENT NET PAYABLE:* *${vendor.balance_formatted}*`);
        lines.push(`--------------------------------`);
        if (vendor.pdf_url) {
            lines.push(`📄 *Official Statement PDF:*`);
            lines.push(vendor.pdf_url);
            lines.push(`--------------------------------`);
        }
        lines.push(`Thank you for your partnership!`);

        try {
            await openWhatsAppChoice(this.dialog, phone, {
                text: lines.join("\n"),
            });
        } catch (err) {
            console.warn("WhatsApp sharing failed:", err);
        }
    }

    onClickDownloadPdf(vendor) {
        if (!vendor.pdf_url) return;
        window.open(vendor.pdf_url, "_blank");
    }
}
