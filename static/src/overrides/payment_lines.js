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
            const remaining = this.currentOrder.remainingDue;
            // If the line has 0 amount, or if there is an unpaid balance remaining on the order,
            // clicking the payment method auto-fills the remaining amount due!
            if (this.pos.currency.isZero(existing.amount) || remaining > 0) {
                const due = this.currentOrder.getDefaultAmountDueToPayIn
                    ? this.currentOrder.getDefaultAmountDueToPayIn(paymentMethod)
                    : remaining;
                const newAmount = this.pos.currency.isZero(existing.amount)
                    ? due
                    : existing.amount + due;
                existing.setAmount(newAmount);
                this.numberBuffer.set(newAmount.toString());
                return true;
            }
            // Order is already fully covered: load amount into buffer for manual keypad adjustments
            this.numberBuffer.set((existing.amount || 0).toString());
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

        const result = await super.addNewPaymentLine(...arguments);

        // Ensure newly created line has the due amount auto-filled if it defaulted to 0
        const newlyAdded = this.paymentLines.find(
            (line) => line.payment_method_id?.id === paymentMethod.id
        );
        if (newlyAdded && this.pos.currency.isZero(newlyAdded.amount) && this.currentOrder.remainingDue > 0) {
            const due = this.currentOrder.getDefaultAmountDueToPayIn
                ? this.currentOrder.getDefaultAmountDueToPayIn(paymentMethod)
                : this.currentOrder.remainingDue;
            newlyAdded.setAmount(due);
            this.numberBuffer.set(due.toString());
        }

        return result;
    },

    selectPaymentLine(uuid) {
        super.selectPaymentLine(...arguments);
        const line = this.paymentLines.find((l) => l.uuid === uuid);
        if (line && this.pos.currency.isZero(line.amount) && this.currentOrder.remainingDue > 0) {
            const due = this.currentOrder.getDefaultAmountDueToPayIn
                ? this.currentOrder.getDefaultAmountDueToPayIn(line.payment_method_id)
                : this.currentOrder.remainingDue;
            line.setAmount(due);
            this.numberBuffer.set(due.toString());
        }
    },
});
