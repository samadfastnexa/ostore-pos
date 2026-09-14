/** @odoo-module **/

import { patch } from "@web/core/utils/patch";
import { _t } from "@web/core/l10n/translation";
import { ControlButtons } from "@point_of_sale/app/screens/product_screen/control_buttons/control_buttons";
import { makeAwaitable } from "@point_of_sale/app/utils/make_awaitable_dialog";
import { AlertDialog } from "@web/core/confirmation_dialog/confirmation_dialog";
import { ReceivePaymentPopup } from "./receive_payment_popup";
import { PaymentReceiptPopup } from "./payment_receipt_popup";

// Take a khata payment without leaving the till.
//
// The shop's objection to sending the cashier to the back office was
// practical: a customer settling their udhaar is standing at the counter with
// a queue behind them, and the cashier is not going to open a second browser
// and sign in. This puts it in the Actions dialog, next to Refund, where the
// same person already goes for the same kind of job.
patch(ControlButtons.prototype, {
    // The customer whose khata this is: the one on the order if there is one,
    // otherwise nobody and the cashier is asked to pick first. Deliberately
    // does NOT invent a customer -- a payment posted against the wrong account
    // is worse than a payment not taken.
    get posRetailKhataPartner() {
        return this.pos.getOrder()?.getPartner();
    },

    // Whether to offer the button at all.
    //
    // Reads the flag the server put on THIS cashier, not on the till account:
    // one shared login stands behind every person at that counter, so asking
    // the browser what it may do would answer the same for all of them.
    //
    // Hiding the button is a courtesy, not the control. The server refuses the
    // same call from a cashier without the permission, however it arrives.
    get posRetailCanTakeKhata() {
        return Boolean(this.pos.getCashier()?._can_khata);
    },

    async onClickKhataPayment() {
        const partner = this.posRetailKhataPartner;
        if (!partner) {
            this.dialog.add(AlertDialog, {
                title: _t("Which customer?"),
                body: _t(
                    "Choose the customer on this order first, then take the khata " +
                        "payment. A payment recorded against the wrong account is " +
                        "harder to undo than it is to avoid."
                ),
            });
            return;
        }

        const paymentResult = await makeAwaitable(this.dialog, ReceivePaymentPopup, {
            partner,
        });

        if (!paymentResult) {
            return;
        }

        this.notification.add(
            _t(
                "%(paid)s received from %(name)s. They now owe %(balance)s.",
                {
                    paid: paymentResult.paid_formatted || (this.env?.utils?.formatCurrency ? this.env.utils.formatCurrency(paymentResult.paid) : paymentResult.paid),
                    name: partner.name,
                    balance: paymentResult.new_balance_formatted || (this.env?.utils?.formatCurrency ? this.env.utils.formatCurrency(paymentResult.new_balance) : paymentResult.new_balance),
                }
            ),
            { type: "success" }
        );

        // Open Printable Payment Receipt modal immediately
        await makeAwaitable(this.dialog, PaymentReceiptPopup, {
            receipt: paymentResult,
        });
    },
});

