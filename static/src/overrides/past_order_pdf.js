/** @odoo-module **/

import { patch } from "@web/core/utils/patch";
import { useState } from "@odoo/owl";
import { _t } from "@web/core/l10n/translation";
import { TicketScreen } from "@point_of_sale/app/screens/ticket_screen/ticket_screen";
import { AlertDialog } from "@web/core/confirmation_dialog/confirmation_dialog";

// A proper PDF receipt for an order that has already been paid.
//
// The receipt screen right after a sale could already share a PDF, but once
// the customer walked away there was no way back to one: the Orders screen
// offered Print Receipt, which only reaches a printer, and a customer asking
// for a copy the next day usually wants it on WhatsApp, not on paper. This
// adds the same PDF to any past order.
//
// Shares where the device can attach a file, downloads where it cannot. The
// share sheet needs a secure context and an OS that offers a target, which
// the shop's HTTPS address now provides on phones and most desktops; a device
// without it still gets the file, rather than a button that does nothing.
patch(TicketScreen.prototype, {
    setup() {
        super.setup(...arguments);
        // Rendering takes the PDF engine a few seconds. Without a busy flag the
        // button sits inert and gets pressed again and again, queueing a render
        // per press.
        this.posRetailPdf = useState({ busy: false });
    },

    posRetailPdfName(order) {
        const ref = (order.pos_reference || order.name || String(order.id)).replace(/[\\/]/g, "-");
        return `Receipt ${ref}.pdf`;
    },

    async posRetailPdfReceipt(order) {
        if (!order?.id || this.posRetailPdf.busy) {
            return;
        }
        this.posRetailPdf.busy = true;
        try {
            // The A4 layout, not the thermal one: this copy is going to be read
            // on a phone or printed on a sheet, and an 80mm strip scaled onto
            // either is unreadable.
            const response = await fetch(`/report/pdf/pos_retail.report_pos_receipt_a4/${order.id}`, {
                credentials: "same-origin",
            });
            if (!response.ok) {
                throw new Error(_t("The receipt could not be produced (%s).", response.status));
            }
            const blob = await response.blob();
            const file = new File([blob], this.posRetailPdfName(order), { type: "application/pdf" });

            if (navigator.canShare?.({ files: [file] })) {
                try {
                    await navigator.share({ files: [file], title: file.name });
                    return;
                } catch (error) {
                    if (error?.name === "AbortError") {
                        return; // the cashier closed the share sheet on purpose
                    }
                    // Any other share failure falls through to a download, so
                    // the cashier still ends up holding the file.
                }
            }
            const url = URL.createObjectURL(blob);
            const link = document.createElement("a");
            link.href = url;
            link.download = file.name;
            document.body.appendChild(link);
            link.click();
            link.remove();
            // Released on the next tick rather than at once: revoking before
            // the browser has started the download cancels it in some engines.
            setTimeout(() => URL.revokeObjectURL(url), 1000);
        } catch (error) {
            this.dialog.add(AlertDialog, {
                title: _t("No PDF receipt"),
                body: error?.message || _t("Please try again."),
            });
        } finally {
            this.posRetailPdf.busy = false;
        }
    },
});
