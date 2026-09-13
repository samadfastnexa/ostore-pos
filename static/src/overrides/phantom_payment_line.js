/** @odoo-module **/

import { patch } from "@web/core/utils/patch";
import { PaymentScreen } from "@point_of_sale/app/screens/payment_screen/payment_screen";

// One click on a payment method must produce exactly one payment line.
//
// Core's `updateSelectedPaymentline` opens with:
//
//     if (this.paymentLines.every((line) => line.paid)) {
//         this.currentOrder.addPaymentline(this.payment_methods_from_config[0]);
//     }
//
// Two distinct bugs converge here:
//
// BUG 1 – Phantom line on empty payment list
// `paid` is not a field on `pos.payment` (not in the JS model nor the Python
// one), so `line.paid` is always `undefined`. `[].every(...)` is vacuously
// true, which means any numpad keypress before a payment method is chosen
// silently creates an unwanted 0.00 line for the first configured method.
//
// BUG 2 – TypeError: Cannot read properties of undefined (reading 'is_cash_count')
// If `payment_methods_from_config` is empty (no methods configured for this
// session/branch), `payment_methods_from_config[0]` is `undefined`. Core then
// passes it straight to `addPaymentline` → `getDefaultAmountDueToPayIn` →
// `shouldRound(paymentMethod)`, which reads `paymentMethod.is_cash_count` —
// crashing with the TypeError seen in production.
//
// Fix: short-circuit `updateSelectedPaymentline` in both situations:
//   • no payment lines yet AND the cashier has not keyed a meaningful amount
//     (prevents phantom-line creation — BUG 1)
//   • no payment methods are configured at all
//     (prevents the undefined-access crash — BUG 2)
patch(PaymentScreen.prototype, {
    updateSelectedPaymentline(amount = false) {
        // BUG 1: no lines + no keyed amount → nothing to update, do nothing.
        if (!this.paymentLines.length && !this.posRetailHasKeyedAmount(amount)) {
            return;
        }
        // BUG 2: no configured payment methods → addPaymentline(undefined) would crash.
        if (!this.payment_methods_from_config?.length) {
            return;
        }
        return super.updateSelectedPaymentline(...arguments);
    },

    /**
     * Whether the cashier has actually keyed a non-zero amount, as opposed to
     * merely touching a key that leaves the buffer empty or at zero.
     *
     * @param {number|false} amount the explicit amount, when core passes one
     * @returns {boolean}
     */
    posRetailHasKeyedAmount(amount) {
        if (amount !== false) {
            return Boolean(parseFloat(amount));
        }
        const buffered = this.numberBuffer.get();
        return Boolean(buffered) && Boolean(parseFloat(buffered));
    },
});
