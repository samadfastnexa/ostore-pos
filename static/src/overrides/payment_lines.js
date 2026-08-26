/** @odoo-module **/

import { patch } from "@web/core/utils/patch";
import { _t } from "@web/core/l10n/translation";
import { PaymentScreen } from "@point_of_sale/app/screens/payment_screen/payment_screen";

// Core appends a tender line on EVERY click of a payment method, with no check
// for what is already on the order (pos_order.js addPaymentline). Two ways that
// goes wrong at a real till:
//
//   * the order is already covered, so each further click piles on a 0.00 line;
//   * the cashier taps Cash repeatedly while keying amounts and ends up with
//     "Cash 2.00 / Cash 5.00 / Cash 223.00" instead of one Cash line for 230.
//
// Both are the same mistake -- a second line for a tender that is already
// there. One line per method is also how the money actually behaves: a single
// drawer, a single card terminal, one figure to reconcile at closing.
//
// Rather than refuse the click, re-select the line that already exists and load
// its amount into the numpad buffer -- the same thing core does after adding a
// line. Tapping Cash twice then means "let me retype the cash amount", which is
// what was almost certainly meant, and the running total stays correct.
patch(PaymentScreen.prototype, {
    async addNewPaymentLine(paymentMethod) {
        const existing = this.paymentLines.find(
            (line) => line.payment_method_id?.id === paymentMethod.id
        );
        if (existing) {
            this.currentOrder.selectPaymentline(existing);
            this.numberBuffer.set((existing.amount || 0).toString());
            this.pos.notification.add(
                _t("%s is already on this order - edit that line instead.", paymentMethod.name),
                { type: "warning" }
            );
            return false;
        }

        // Nothing left to pay: a further tender could only ever be 0.00.
        // Refunds are exempt -- their balance is negative, never zero.
        if (
            this.paymentLines.length &&
            !this.isRefundOrder &&
            this.currentOrder?.orderHasZeroRemaining
        ) {
            this.pos.notification.add(
                _t("This order is already fully paid. Change or remove a tender to pay it differently."),
                { type: "warning" }
            );
            return false;
        }

        return await super.addNewPaymentLine(...arguments);
    },
});
