/** @odoo-module **/

import { patch } from "@web/core/utils/patch";
import { useState } from "@odoo/owl";
import { _t } from "@web/core/l10n/translation";
import { useService } from "@web/core/utils/hooks";
import { ReceiptScreen } from "@point_of_sale/app/screens/receipt_screen/receipt_screen";
import { openWhatsAppChoice } from "../backend/whatsapp_choice_dialog";

// Send the receipt over WhatsApp.
//
// Email is the only sharing route core offers, and almost no walk-in customer
// at a hardware counter has given an email address -- but nearly all of them
// have WhatsApp. The number is usually already on the customer record for the
// khata, so in the common case this is one tap.
//
// The receipt is sent as TEXT rather than a link. A link would need a public
// HTTPS URL for the order, and this shop runs on a bare IP with no domain and
// no certificate; a customer would get a browser warning, if the page loaded
// at all. Plain text arrives intact on every phone and can be searched later
// in the chat, which is what a customer actually does with a receipt.
patch(ReceiptScreen.prototype, {
    setup() {
        super.setup(...arguments);
        this.dialog = useService("dialog");
        // Rendering the PDF takes wkhtmltopdf a few seconds, during which the
        // button used to sit inert -- so people clicked it again and again,
        // queueing a render per click. Reactive busy flag: the template swaps
        // in a spinner and disables the button until the share sheet closes.
        this.posRetailWa = useState({ busy: false });
    },

    /**
     * The customer's number in the international form wa.me needs: digits
     * only, country code first, no plus sign.
     * Returns "" when there is no usable number -- WhatsApp then opens with
     * the message ready and lets the cashier pick the contact, which is the
     * right fallback for a walk-in.
     */
    get posRetailWhatsappNumber() {
        const raw = this.currentOrder?.getPartner()?.phone
            || this.currentOrder?.getPartner()?.mobile
            || "";
        let digits = String(raw).replace(/\D/g, "");
        if (!digits) {
            return "";
        }
        // 0092... or 0092... -> drop the international access prefix.
        if (digits.startsWith("00")) {
            digits = digits.slice(2);
            return digits;
        }
        // A local number written with a trunk "0" (0322 ...) needs the country
        // code in its place. Taken from the company's own country rather than
        // hardcoded, so this is not Pakistan-only.
        const code = String(this.pos.company?.country_id?.phone_code || "").replace(/\D/g, "");
        if (digits.startsWith("0")) {
            return code ? code + digits.slice(1) : digits.slice(1);
        }
        // Already looks international if it is longer than a local subscriber
        // number; otherwise assume local and prepend the code.
        if (code && digits.length <= 10 && !digits.startsWith(code)) {
            return code + digits;
        }
        return digits;
    },

    /** The public URL to view/download the PDF receipt. */
    get posRetailReceiptPdfUrl() {
        const order = this.currentOrder;
        if (!order) {
            return "";
        }
        const origin = window.location.origin;
        if (order.access_token) {
            return `${origin}/pos_retail/portal/receipt/pdf/${order.access_token}`;
        }
        if (order.id) {
            return `${origin}/pos_retail/portal/receipt/pdf/${order.id}`;
        }
        return "";
    },

    /** The receipt as a WhatsApp message. *asterisks* render as bold there. */
    get posRetailWhatsappText() {
        const order = this.currentOrder;
        if (!order) {
            return "";
        }
        const fmt = (v) => this.env.utils.formatCurrency(v || 0);
        const lines = [];

        const shopName = this.pos.company?.name || "";
        if (shopName) {
            lines.push("*" + shopName + "*");
        }

        const isRefund = order.isRefund || (order.priceIncl < 0) || (order.totalDue < 0);
        if (isRefund) {
            lines.push("*CREDIT RETURN RECEIPT*");
        }

        const ref = order.pos_reference || order.name || "";
        if (ref) {
            lines.push((isRefund ? "Return Receipt: " : "Receipt: ") + ref);
        }

        const dateStr = order.date_order
            ? (typeof order.date_order.toFormat === "function"
                ? order.date_order.toFormat("dd/MM/yyyy HH:mm")
                : String(order.date_order).slice(0, 16))
            : "";
        if (dateStr) {
            lines.push("Date: " + dateStr);
        }

        const cashierName = order.getCashierName?.() || this.pos.user?.name || "";
        if (cashierName) {
            lines.push("Cashier: " + cashierName);
        }

        const partner = order.getPartner();
        if (partner) {
            lines.push("Customer: " + partner.name);
            if (partner.pos_outstanding_balance !== undefined) {
                lines.push("Khata Balance: " + fmt(partner.pos_outstanding_balance));
            }
        }

        lines.push("");

        for (const line of order.getOrderlines() || []) {
            const qty = line.getQuantityStr?.()?.unitPart ?? line.qty;
            const name = line.full_product_name || line.product_id?.display_name || "";
            const price = line.currencyDisplayPrice || fmt(line.price_subtotal_incl || line.price_unit * line.qty);
            lines.push(`${qty} x ${name}   ${price}`);
        }

        lines.push("");
        lines.push("*TOTAL  " + fmt(order.priceIncl ?? order.totalDue) + "*");

        const pdfUrl = this.posRetailReceiptPdfUrl;
        if (pdfUrl) {
            lines.push("");
            lines.push("📄 *Download Official PDF Receipt:*");
            lines.push(pdfUrl);
        }

        const thanks = this.pos.config.pos_retail_receipt_thankyou;
        if (thanks) {
            lines.push("");
            lines.push(thanks);
        }
        return lines.join("\n");
    },

    async posRetailShareOnWhatsapp() {
        if (this.posRetailWa.busy) {
            return;
        }
        this.posRetailWa.busy = true;
        try {
            await this._posRetailShareOnWhatsapp();
        } finally {
            this.posRetailWa.busy = false;
        }
    },

    async _posRetailShareOnWhatsapp() {
        const order = this.currentOrder;
        if (!order) {
            return;
        }
        const number = this.posRetailWhatsappNumber;
        const isRefund = order.isRefund || (order.priceIncl < 0) || (order.totalDue < 0);
        const ref = String(order.pos_reference || order.name || "receipt").replace(/[\\/]/g, "-");
        const filename = `${isRefund ? "Return_Receipt" : "Receipt"}_${ref}.pdf`;

        try {
            // 1. Fetch PDF blob directly
            const pdfEndpoint = order.id
                ? `/report/pdf/pos_retail.report_pos_receipt_a4/${order.id}`
                : (order.access_token ? `/pos_retail/portal/receipt/pdf/${order.access_token}` : null);
            if (!pdfEndpoint) {
                throw new Error(_t("No valid receipt reference found for this order."));
            }

            const res = await fetch(pdfEndpoint, { credentials: "same-origin" });
            if (!res.ok) {
                throw new Error(_t("Could not generate receipt PDF (Status %s).", res.status));
            }
            const pdfBlob = await res.blob();
            if (!pdfBlob || pdfBlob.size === 0) {
                throw new Error(_t("The generated receipt PDF was empty."));
            }

            // 2. Prompt every time: WhatsApp Web vs WhatsApp App (zero saved selection)
            const shared = await openWhatsAppChoice(this.dialog || this.env.services.dialog, number, {
                blob: pdfBlob,
                filename: filename,
            });
            if (shared) {
                this.notification.add(
                    _t("Receipt PDF processed for WhatsApp sharing."),
                    { type: "info" }
                );
            }
        } catch (err) {
            console.error("pos_retail: WhatsApp receipt share failed", err);
            this.notification.add(
                err?.message || _t("Could not generate or share receipt PDF. Please verify connection."),
                { type: "danger" }
            );
        }
    },
});
