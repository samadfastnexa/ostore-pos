/** @odoo-module **/

import { patch } from "@web/core/utils/patch";
import { useState } from "@odoo/owl";
import { _t } from "@web/core/l10n/translation";
import { ReceiptScreen } from "@point_of_sale/app/screens/receipt_screen/receipt_screen";

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

    /** The receipt as a WhatsApp message. *asterisks* render as bold there. */
    get posRetailWhatsappText() {
        const order = this.currentOrder;
        const fmt = (v) => this.env.utils.formatCurrency(v || 0);
        const lines = [];

        const shopName = this.pos.company?.name || "";
        if (shopName) {
            lines.push("*" + shopName + "*");
        }
        const ref = order.pos_reference || order.name || "";
        if (ref) {
            lines.push("Receipt " + ref);
        }
        if (order.formattedValidationDate) {
            lines.push(order.formattedValidationDate);
        }
        lines.push("");

        for (const line of order.getOrderlines() || []) {
            const qty = line.getQuantityStr?.()?.unitPart ?? line.qty;
            lines.push(`${qty} x ${line.full_product_name}   ${line.currencyDisplayPrice}`);
        }

        lines.push("");
        lines.push("*TOTAL  " + fmt(order.priceIncl ?? order.totalDue) + "*");

        const thanks = this.pos.config.pos_retail_receipt_thankyou;
        if (thanks) {
            lines.push("");
            lines.push(thanks);
        }
        return lines.join("\n");
    },

    /**
     * Share the receipt PDF itself through the operating system's share sheet,
     * which is the only way a file can reach WhatsApp from a web page: the
     * wa.me URL scheme carries text and nothing else, so no amount of URL
     * building will ever attach a document.
     *
     * Returns false when it cannot be done, so the caller can fall back:
     *   - navigator.share with files needs a SECURE CONTEXT. On localhost that
     *     is satisfied; on the production server, which is a bare IP over
     *     plain http, navigator.share is simply undefined. Same rule that
     *     hides the POS camera scanner there.
     *   - Firefox on the desktop has no file sharing at all.
     *   - The order must have been synced, or there is no id to render from.
     */
    async posRetailSharePdf() {
        const order = this.currentOrder;
        if (!order?.id || typeof navigator === "undefined") {
            return false;
        }
        if (!navigator.share || !navigator.canShare) {
            return false;
        }
        try {
            const res = await fetch(
                `/report/pdf/pos_retail.report_pos_receipt_a4/${order.id}`,
                { credentials: "same-origin" }
            );
            if (!res.ok) {
                return false;
            }
            const blob = await res.blob();
            const ref = String(order.pos_reference || order.name || "receipt").replace(/[\\/]/g, "-");
            const file = new File([blob], `Receipt ${ref}.pdf`, { type: "application/pdf" });
            if (!navigator.canShare({ files: [file] })) {
                return false;
            }
            await navigator.share({
                files: [file],
                title: `Receipt ${ref}`,
                text: this.posRetailWhatsappText,
            });
            return true;
        } catch (err) {
            // ONLY a dismissed share sheet counts as handled. An earlier
            // version returned true for every error, so a failed PDF fetch or
            // an unsupported browser looked like a successful share, the
            // fallback was skipped, and the button did nothing at all with no
            // hint as to why.
            if (err && err.name === "AbortError") {
                return true;
            }
            console.warn("pos_retail: WhatsApp PDF share failed, falling back", err);
            return false;
        }
    },

    /** wa.me carries text only. Opened via window.open so the POS stays put. */
    posRetailOpenWhatsappText() {
        const number = this.posRetailWhatsappNumber;
        const text = encodeURIComponent(this.posRetailWhatsappText);
        const url = number
            ? `https://wa.me/${number}?text=${text}`
            : `https://wa.me/?text=${text}`;
        const win = window.open(url, "_blank", "noopener,noreferrer");
        if (!win) {
            // Blocked. Say so rather than leaving a button that looks dead.
            this.notification.add(
                _t("WhatsApp could not be opened. Allow pop-ups for this site and try again."),
                { type: "warning" }
            );
        }
    },

    async posRetailShareOnWhatsapp() {
        if (this.posRetailWa.busy) {
            return;
        }
        this.posRetailWa.busy = true;
        try {
            await this._posRetailShareOnWhatsapp();
        } finally {
            // navigator.share resolves when the sheet closes, so busy covers
            // the whole interaction, not just the fetch.
            this.posRetailWa.busy = false;
        }
    },

    async _posRetailShareOnWhatsapp() {
        // Decided BEFORE any await. window.open called after an await has left
        // the user-gesture window and is blocked as a pop-up, so when this
        // browser cannot share files at all the text route has to be taken
        // straight away, while the click is still live.
        const canShareFiles =
            typeof navigator !== "undefined" && !!navigator.share && !!navigator.canShare;
        if (!canShareFiles) {
            this.notification.add(
                _t("This device cannot attach files to WhatsApp, so the receipt is being sent as a message. Attaching the PDF needs the shop to be on https."),
                { type: "info" }
            );
            this.posRetailOpenWhatsappText();
            return;
        }
        if (await this.posRetailSharePdf()) {
            return;
        }
        this.posRetailOpenWhatsappText();
    },
});
