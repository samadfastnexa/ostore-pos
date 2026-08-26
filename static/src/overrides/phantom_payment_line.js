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
// `paid` is not a field on `pos.payment` -- not in the JS model
// (point_of_sale/static/src/app/models/pos_payment.js) and not in the Python
// one -- so `line.paid` is always `undefined`. The callback is therefore always
// falsy, which means the guard can never pass on a non-empty list and can ONLY
// pass on an EMPTY one, where `[].every(...)` is vacuously true.
//
// The practical effect: the numpad sits on the payment screen from the moment
// it opens, and every numpad or keyboard key routes through
// `updateSelectedPaymentline` (via the number buffer's `triggerAtInput`). So a
// single keypress made BEFORE any payment method has been chosen silently
// creates a payment line for whatever method happens to be first in the config
// -- Cash on this register -- and the remainder of that same call immediately
// writes the buffer's value onto it, giving 0.00 when the key was Backspace,
// "0" or the decimal point. The cashier never asked for that line, does not
// read it as one, then clicks Cash for real and ends up looking at two Cash
// lines: a phantom 0.00 and the genuine one.
//
// With no payment lines there is by definition no "selected payment line" to
// update, so the honest answer is to do nothing -- unless the cashier really
// did key an amount first, which is a deliberate "tender this much in cash"
// gesture and is left working exactly as before.
patch(PaymentScreen.prototype, {
    updateSelectedPaymentline(amount = false) {
        if (!this.paymentLines.length && !this.posRetailHasKeyedAmount(amount)) {
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
