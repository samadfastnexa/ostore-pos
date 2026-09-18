/** @odoo-module **/

import { Component, useState } from "@odoo/owl";
import { Dialog } from "@web/core/dialog/dialog";
import { _t } from "@web/core/l10n/translation";
import { usePos } from "@point_of_sale/app/hooks/pos_hook";
import { useService } from "@web/core/utils/hooks";

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

        const text = this.whatsappShareText;
        const phone = this.customerPhone;
        const ref = (this.receipt.payment_name || `Payment_${this.receipt.payment_id || ""}`).replace(/[\\/]/g, "-");
        const filename = `Payment_Receipt_${ref}.pdf`;

        // Claim popup window synchronously to prevent popup blocker
        const canShareFiles = typeof navigator !== "undefined" && !!navigator.share && !!navigator.canShare;
        let win = null;
        if (!canShareFiles) {
            win = window.open("about:blank", "_blank");
        }

        try {
            let blob = null;
            if (this.receipt.payment_id) {
                try {
                    const tokenPart = this.receipt.payment_token ? `?token=${this.receipt.payment_token}` : "";
                    const res = await fetch(`/pos_retail/portal/payment/pdf/${this.receipt.payment_id}${tokenPart}`, {
                        credentials: "same-origin",
                    });
                    if (res.ok) {
                        blob = await res.blob();
                    }
                } catch (blobErr) {
                    console.warn("pos_retail: could not fetch payment receipt PDF blob", blobErr);
                }
            }

            // 1. Native mobile share sheet: share PDF file ONLY
            if (canShareFiles && blob) {
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
                    if (err && err.name === "AbortError") return;
                    console.warn("pos_retail: native payment share failed, falling back", err);
                }
            }

            // 2. Desktop fallback: automatically download the PDF file
            if (blob) {
                try {
                    const blobUrl = URL.createObjectURL(blob);
                    const a = document.createElement("a");
                    a.href = blobUrl;
                    a.download = filename;
                    document.body.appendChild(a);
                    a.click();
                    document.body.removeChild(a);
                    URL.revokeObjectURL(blobUrl);
                } catch (dlErr) {
                    console.warn("pos_retail: automatic PDF download failed", dlErr);
                }
            }

            // 3. Open WhatsApp Web directly to customer's chat
            const url = phone
                ? `https://web.whatsapp.com/send?phone=${phone}`
                : `https://web.whatsapp.com/`;

            if (win && !win.closed) {
                win.location = url;
            } else {
                window.open(url, "_blank", "noopener,noreferrer");
            }

            this.notification.add(
                _t("Payment receipt PDF downloaded! WhatsApp opened. Please attach or drag & drop the PDF into the chat."),
                { type: "success" }
            );
        } catch (err) {
            console.warn("pos_retail: payment receipt WhatsApp share failed", err);
            if (win && !win.closed) win.close();
            this.notification.add(_t("Could not open WhatsApp."), { type: "warning" });
        } finally {
            this.state.sharingWa = false;
        }
    }
}
