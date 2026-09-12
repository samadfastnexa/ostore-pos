/** @odoo-module **/

import { patch } from "@web/core/utils/patch";
import { _t } from "@web/core/l10n/translation";
import { OrderReceipt } from "@point_of_sale/app/screens/receipt_screen/receipt/order_receipt";
import { generateQRCodeDataUrl } from "@point_of_sale/utils";

patch(OrderReceipt.prototype, {
    // --- columned invoice layout (Receipt Studio style "invoice") -----------

    /** Total discount given on this sale, or false when there was none. */
    get posRetailInvoiceDiscount() {
        const order = this.order;
        const discountLines = order.discountLines || [];
        const lines = (order.getOrderlines() || []).filter(
            (line) => !discountLines.includes(line)
        );
        // Sum what each line would have cost without its discount, less what it
        // actually cost. displayPriceNoDiscount is the same figure core prints
        // in its own "45% discount off on 202.00" sentence, so the two agree.
        const perLine = lines.reduce(
            (sum, line) => sum + ((line.displayPriceNoDiscount || 0) - (line.displayPrice || 0)),
            0
        );
        // Plus the order-level discount, which is not a percentage sitting on a
        // line but a negative line of its own, so the sum above cannot see it.
        // That is what the "Discount the rest" button produces and it is
        // usually the ONLY discount on the bill -- omitting it printed a
        // receipt showing a reduced total with nothing to explain the drop.
        const global = discountLines.reduce(
            (sum, line) => sum + Math.abs(line.displayPrice || 0),
            0
        );
        const total = perLine + global;
        if (!total || order.currency.isZero(total)) {
            return false;
        }
        return this.formatCurrency(total);
    },

    /** Raw balance the customer owed BEFORE this sale, as a number. */
    get posRetailPreviousBalanceAmount() {
        const partner = this.order.getPartner();
        if (!partner) {
            return 0;
        }
        // Loaded onto the partner at session start (res_partner.py). It is a
        // snapshot rather than live, which is honest for a printed slip: it is
        // the balance as at the start of the shift, and today's sale is listed
        // above it either way.
        return partner.pos_outstanding_balance || 0;
    },

    get posRetailPreviousBalance() {
        const amount = this.posRetailPreviousBalanceAmount;
        if (!amount || this.order.currency.isZero(amount)) {
            return false;
        }
        return this.formatCurrency(amount);
    },

    /** This sale plus anything already outstanding -- what they owe in total. */
    get posRetailAmountWithBalance() {
        const total = this.order.priceIncl || 0;
        return this.formatCurrency(total + this.posRetailPreviousBalanceAmount);
    },

    /**
     * The Credit Return section of a refund receipt: what this undoes, how
     * the money actually went back, who authorised it, and -- only when it
     * genuinely touched the customer's account -- what that account stood at
     * before and after. Mirrors _pos_retail_credit_return_info() on the
     * server (pos_order.py), computed here instead of over RPC because a
     * receipt has to be printable with no connectivity at all.
     *
     * The balance figures carry the same caveat as posRetailPreviousBalance
     * above: partner.pos_outstanding_balance is a snapshot loaded at session
     * start, not a live read, and the credit itself only becomes posted
     * truth once the till session closes -- an estimate on paper, not a
     * closed book.
     */
    get posRetailCreditReturnInfo() {
        const order = this.order;
        if (!order.is_refund) {
            return false;
        }

        // One entry per distinct original order this return's lines point
        // back to -- usually one, but a single no-receipt return popup only
        // ever links one line at a time, so a customer bringing back items
        // from two different visits in one go would show both.
        const originals = new Map();
        for (const line of order.getOrderlines() || []) {
            const origOrder = line.refunded_orderline_id?.order_id;
            if (origOrder && !originals.has(origOrder.id)) {
                originals.set(origOrder.id, {
                    reference: origOrder.pos_reference || origOrder.name,
                    date: origOrder.formatDateOrTime
                        ? origOrder.formatDateOrTime("date_order")
                        : "",
                });
            }
        }

        const creditPayment = this.paymentLines.find(
            (p) => p.payment_method_id?.type === "pay_later"
        );
        const refundAmount = Math.abs(order.priceIncl || 0);

        const info = {
            originalOrders: [...originals.values()],
            authorizedBy: order.pos_retail_return_manager_id?.name || false,
            refundAmount: this.formatCurrency(refundAmount),
        };

        if (creditPayment) {
            info.disposition = _t("Credited to %s", creditPayment.payment_method_id.name);
            const before = this.posRetailPreviousBalanceAmount;
            info.hasBalance = true;
            info.balanceBefore = this.formatCurrency(before);
            info.balanceAfter = this.formatCurrency(before - refundAmount);
        } else {
            const methodNames = this.paymentLines
                .map((p) => p.payment_method_id?.name)
                .filter(Boolean);
            info.hasBalance = false;
            info.disposition = methodNames.length ? methodNames.join(", ") : _t("Not yet paid");
        }
        return info;
    },

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
