/** @odoo-module **/

import { Component, onWillStart, useState } from "@odoo/owl";
import { Dialog } from "@web/core/dialog/dialog";
import { _t } from "@web/core/l10n/translation";
import { usePos } from "@point_of_sale/app/hooks/pos_hook";
import { useService } from "@web/core/utils/hooks";
import { openWhatsAppChoice } from "../backend/whatsapp_choice_dialog";

/**
 * Interactive POS Dialog for paying vendors from the till drawer or bank.
 * Cashiers can record outbound payments, settle vendor bills, print receipts,
 * and share structured payment confirmations and PDF receipts to WhatsApp.
 */
export class PosRetailVendorPaymentPopup extends Component {
    static template = "pos_retail.VendorPaymentPopup";
    static components = { Dialog };
    static props = {
        close: Function,
        vendor: Object,
        onPaymentDone: { type: Function, optional: true },
    };

    setup() {
        this.parseFloat = parseFloat;
        this.pos = usePos();
        this.dialog = useService("dialog");
        this.notification = useService("notification");

        const vendor = this.props.vendor;
        const initialOwed = vendor.balance || 0;
        const todayStr = new Date().toISOString().split("T")[0];

        this.state = useState({
            amount: initialOwed > 0 ? String(initialOwed) : "",
            journals: [],
            journalId: false,
            date: todayStr,
            memo: "",
            submitting: false,
            errorMsg: "",
            completedReceipt: null,
            sharingWa: false,
        });

        this.loadJournals();
    }

    get vendor() {
        return this.props.vendor;
    }

    get previousBalance() {
        return this.vendor.balance || 0;
    }

    get newBalancePreview() {
        const amt = parseFloat(this.state.amount) || 0;
        return this.previousBalance - amt;
    }

    get canConfirm() {
        if (this.state.submitting) return false;
        const val = parseFloat(this.state.amount);
        return !isNaN(val) && val > 0;
    }

    formatCurrency(amount) {
        const val = typeof amount === "number" ? amount : parseFloat(amount) || 0;
        if (this.env?.utils?.formatCurrency) {
            return this.env.utils.formatCurrency(val);
        }
        return val.toFixed(2);
    }

    loadJournals() {
        const pms = this.pos.payment_methods_from_config ||
                    (this.pos.models["pos.payment.method"] ? this.pos.models["pos.payment.method"].getAll() : []);
        const validPms = (pms || []).filter(
            (p) => p.type !== "pay_later" && !/credit|khata|udhar|on account/i.test(p.name || "")
        );
        this.state.journals = validPms.map((p) => ({
            id: p.id,
            name: p.name,
            type: p.is_cash_count ? "cash" : "bank",
            is_cash: Boolean(p.is_cash_count),
        }));
        if (this.state.journals.length) {
            const defaultCash = this.state.journals.find((j) => j.is_cash) || this.state.journals[0];
            this.state.journalId = defaultCash ? defaultCash.id : this.state.journals[0].id;
        }
    }

    onAmountInput(ev) {
        this.state.amount = ev.target.value;
    }

    setFullAmount() {
        const owed = Math.max(0, this.previousBalance);
        this.state.amount = String(owed);
    }

    setJournal(id) {
        this.state.journalId = id;
    }

    async onConfirm() {
        const amount = parseFloat(this.state.amount);
        if (!amount || amount <= 0) {
            this.state.errorMsg = _t("Please enter a valid payment amount greater than zero.");
            return;
        }

        this.state.submitting = true;
        this.state.errorMsg = "";
        try {
            const cashier = this.pos.getCashier();
            const result = await this.pos.data.call(
                "res.partner",
                "pos_retail_pay_vendor",
                [
                    this.vendor.id,
                    amount,
                    this.pos.config.id,
                    cashier?.id || false,
                    this.state.journalId,
                    this.state.memo,
                    this.state.date,
                ]
            );

            // Update vendor in local view
            this.vendor.balance = result.new_balance;
            this.vendor.balance_formatted = result.new_balance_formatted;

            this.state.completedReceipt = result;

            this.notification.add(
                _t("%(paid)s paid to vendor %(name)s. Remaining balance: %(balance)s.", {
                    paid: result.paid_formatted,
                    name: this.vendor.name,
                    balance: result.new_balance_formatted,
                }),
                { type: "success" }
            );

            if (typeof this.props.onPaymentDone === "function") {
                this.props.onPaymentDone(result);
            }
        } catch (error) {
            this.state.errorMsg =
                error?.data?.message ||
                error?.message ||
                _t("The vendor payment could not be processed.");
        } finally {
            this.state.submitting = false;
        }
    }

    async onShareWhatsApp() {
        const receipt = this.state.completedReceipt;
        if (!receipt) return;

        this.state.sharingWa = true;
        try {
            await openWhatsAppChoice(this.dialog, receipt.partner_phone || "", {
                text: receipt.whatsapp_text || "",
            });
        } catch (e) {
            console.warn("WhatsApp share error:", e);
        } finally {
            this.state.sharingWa = false;
        }
    }

    printReceipt() {
        const receipt = this.state.completedReceipt;
        if (!receipt || !receipt.payment_id) {
            window.print();
            return;
        }

        const url = `/pos_retail/print_report?report=pos_retail.report_pos_retail_payment_receipt&id=${receipt.payment_id}`;
        let iframe = document.getElementById("pos_retail_direct_print_frame");
        if (!iframe) {
            iframe = document.createElement("iframe");
            iframe.id = "pos_retail_direct_print_frame";
            iframe.style.position = "fixed";
            iframe.style.right = "0";
            iframe.style.bottom = "0";
            iframe.style.width = "0";
            iframe.style.height = "0";
            iframe.style.border = "0";
            document.body.appendChild(iframe);
        }
        iframe.onload = () => {
            setTimeout(() => {
                try {
                    iframe.contentWindow.focus();
                    iframe.contentWindow.print();
                } catch (e) {
                    console.warn("Direct iframe print failed, falling back to window.print:", e);
                    window.print();
                }
            }, 250);
        };
        iframe.src = url;
    }
}
