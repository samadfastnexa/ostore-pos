/** @odoo-module **/

import { Component, useState } from "@odoo/owl";
import { Dialog } from "@web/core/dialog/dialog";
import { _t } from "@web/core/l10n/translation";
import { usePos } from "@point_of_sale/app/hooks/pos_hook";
import { useService } from "@web/core/utils/hooks";
import { openWhatsAppChoice } from "../backend/whatsapp_choice_dialog";

/**
 * Customer Payment Receipt Modal with complete audit breakdown, print support,
 * and WhatsApp sharing (PDF + text).
 */
export class PaymentReceiptPopup extends Component {
    static template = "pos_retail.PaymentReceiptPopup";
    static components = { Dialog };
    static props = {
        close: Function,
        receipt: Object,
    };

    setup() {
        this.pos = usePos();
        this.dialog = useService("dialog");
        this.notification = useService("notification");
        this.state = useState({ sharingWa: false });
    }

    get receipt() {
        return this.props.receipt || {};
    }

    printReceipt() {
        if (this.receipt.payment_id) {
            const url = `/pos_retail/print_report?report=pos_retail.report_pos_retail_payment_receipt&id=${this.receipt.payment_id}`;
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
        } else {
            window.print();
        }
    }

    get whatsappShareText() {
        const r = this.receipt;
        const lines = [];
        const branch = r.branch_name || this.pos.company?.name || "STORE";
        lines.push(`*${branch}*`);
        lines.push(`*CUSTOMER PAYMENT RECEIPT*`);
        if (r.payment_name) lines.push(`Receipt Ref: ${r.payment_name}`);
        lines.push(`Date: ${r.datetime || r.date || ""}`);
        if (r.cashier_name) lines.push(`Cashier: ${r.cashier_name}`);
        if (r.partner_name) lines.push(`Customer: ${r.partner_name}`);
        if (r.journal_name) lines.push(`Payment Method: ${r.journal_name}`);
        if (r.memo) lines.push(`Note: ${r.memo}`);
        lines.push(`--------------------------------`);
        if (r.previous_balance_formatted) lines.push(`Previous Balance: ${r.previous_balance_formatted}`);
        lines.push(`*AMOUNT RECEIVED: ${r.paid_formatted}*`);
        lines.push(`*NEW BALANCE OWED: ${r.new_balance_formatted}*`);
        lines.push(`--------------------------------`);

        if (r.allocations && r.allocations.length) {
            lines.push(`*Debt Allocation:*`);
            for (const item of r.allocations) {
                lines.push(`• ${item.name} (${item.date}): Paid ${item.applied_amount_formatted}, Remaining ${item.remaining_balance_formatted}`);
            }
            lines.push(`--------------------------------`);
        }

        const pdfUrl = this.receiptPdfUrl;
        if (pdfUrl) {
            lines.push(`📄 *Official Payment Receipt PDF:*`);
            lines.push(pdfUrl);
            lines.push(`--------------------------------`);
        }
        lines.push(`Thank you for settling your khata account!`);
        return lines.join("\n");
    }

    get receiptPdfUrl() {
        const r = this.receipt;
        if (r.pdf_url) return r.pdf_url;
        if (r.payment_id) {
            const origin = window.location.origin;
            const tokenPart = r.payment_token ? `?token=${r.payment_token}` : "";
            return `${origin}/pos_retail/portal/payment/pdf/${r.payment_id}${tokenPart}`;
        }
        return "";
    }

    get customerPhone() {
        const raw = this.receipt.partner_phone || "";
        let digits = String(raw).replace(/\D/g, "");
        if (!digits) return "";
        if (digits.startsWith("00")) return digits.slice(2);
        const code = String(this.pos.company?.country_id?.phone_code || "").replace(/\D/g, "");
        if (digits.startsWith("0")) {
            return code ? code + digits.slice(1) : digits.slice(1);
        }
        if (code && digits.length <= 10 && !digits.startsWith(code)) {
            return code + digits;
        }
        return digits;
    }

    async shareWhatsApp() {
        if (this.state.sharingWa) return;
        this.state.sharingWa = true;

        const phone = this.customerPhone;
        const ref = (this.receipt.payment_name || `Payment_${this.receipt.payment_id || ""}`).replace(/[\\/]/g, "-");
        const filename = `Payment_Receipt_${ref}.pdf`;

        try {
            if (!this.receipt.payment_id) {
                throw new Error(_t("No valid payment ID found to generate receipt."));
            }

            const tokenPart = this.receipt.payment_token ? `?token=${this.receipt.payment_token}` : "";
            const res = await fetch(`/pos_retail/portal/payment/pdf/${this.receipt.payment_id}${tokenPart}`, {
                credentials: "same-origin",
            });
            if (!res.ok) {
                throw new Error(_t("Could not generate payment receipt PDF (Status %s).", res.status));
            }
            const blob = await res.blob();
            if (!blob || blob.size === 0) {
                throw new Error(_t("Generated payment receipt PDF was empty."));
            }

            // 1. Native mobile share sheet: share PDF file ONLY
            if (typeof navigator !== "undefined" && typeof navigator.share === "function" && typeof navigator.canShare === "function") {
                try {
                    const file = new File([blob], filename, { type: "application/pdf" });
                    if (navigator.canShare({ files: [file] })) {
                        await navigator.share({
                            files: [file],
                            title: filename,
                        });
                        this.notification.add(_t("Payment receipt PDF shared successfully on WhatsApp."), { type: "success" });
                        return;
                    }
                } catch (err) {
                    if (err && err.name === "AbortError") {
                        return; // User dismissed share sheet
                    }
                    console.warn("pos_retail: native payment share failed, falling back", err);
                }
            }

            // 2. Desktop fallback: automatically download the PDF file
            try {
                const blobUrl = URL.createObjectURL(blob);
                const a = document.createElement("a");
                a.href = blobUrl;
                a.download = filename;
                document.body.appendChild(a);
                a.click();
                document.body.removeChild(a);
                setTimeout(() => URL.revokeObjectURL(blobUrl), 2000);
            } catch (dlErr) {
                console.warn("pos_retail: automatic PDF download failed", dlErr);
            }

            // 3. Prompt every time: WhatsApp Web vs WhatsApp App (zero saved selection)
            await openWhatsAppChoice(this.dialog, phone);
            this.notification.add(
                _t("The payment receipt PDF has been downloaded so you can attach it in WhatsApp."),
                { type: "info" }
            );
        } catch (err) {
            console.warn("pos_retail: payment receipt WhatsApp share failed", err);
            this.notification.add(
                err?.message || _t("Could not generate or share payment receipt PDF. Please check connection."),
                { type: "danger" }
            );
        } finally {
            this.state.sharingWa = false;
        }
    }
}
