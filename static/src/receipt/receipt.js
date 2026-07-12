/** @odoo-module **/

import { patch } from "@web/core/utils/patch";
import { OrderReceipt } from "@point_of_sale/app/screens/receipt_screen/receipt/order_receipt";
import { generateQRCodeDataUrl } from "@point_of_sale/utils";

patch(OrderReceipt.prototype, {
    /**
     * QR code printed on the receipt. Encodes the order's unique reference so a
     * cashier can scan it to look the sale up (returns / verification).
     * Rendered entirely client-side, so it works offline.
     */
    get posRetailReceiptQR() {
        try {
            const ref =
                this.order.pos_reference ||
                this.order.name ||
                this.order.ticket_code ||
                this.order.uuid ||
                "";
            if (!ref) {
                return false;
            }
            return generateQRCodeDataUrl(String(ref));
        } catch {
            return false;
        }
    },
});
