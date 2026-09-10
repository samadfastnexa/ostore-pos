/** @odoo-module **/

import { patch } from "@web/core/utils/patch";
import { _t } from "@web/core/l10n/translation";
import { ControlButtons } from "@point_of_sale/app/screens/product_screen/control_buttons/control_buttons";
import { makeAwaitable } from "@point_of_sale/app/utils/make_awaitable_dialog";
import { NumberPopup } from "@point_of_sale/app/components/popups/number_popup/number_popup";
import { AlertDialog } from "@web/core/confirmation_dialog/confirmation_dialog";

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

        const owed = partner.pos_outstanding_balance || 0;
        const amount = await makeAwaitable(this.dialog, NumberPopup, {
            title: _t("Khata payment from %s", partner.name),
            subtitle:
                owed > 0
                    ? _t("Currently owes %s", this.env.utils.formatCurrency(owed))
                    : _t("Nothing outstanding — this will leave them in credit"),
            startingValue: owed > 0 ? owed : 0,
        });
        if (!amount || parseFloat(amount) <= 0) {
            return;
        }

        try {
            const result = await this.pos.data.call(
                "pos.retail.khata.payment",
                "pos_retail_settle_from_pos",
                [partner.id, parseFloat(amount), this.pos.getCashier().id]
            );
            // The balance is read back from the server rather than subtracted
            // here. The payment settles the oldest debts first and can leave a
            // customer in credit, so arithmetic done in the browser would
            // disagree with the ledger on exactly the cases that matter.
            partner.pos_outstanding_balance = result.balance;
            this.notification.add(
                _t(
                    "%(paid)s received from %(name)s. They now owe %(balance)s.",
                    {
                        paid: this.env.utils.formatCurrency(result.paid),
                        name: partner.name,
                        balance: this.env.utils.formatCurrency(result.balance),
                    }
                ),
                { type: "success" }
            );
        } catch (error) {
            // Shown rather than swallowed: the cashier has money in their hand
            // and has to know whether it was recorded.
            this.dialog.add(AlertDialog, {
                title: _t("Payment not recorded"),
                body:
                    error?.data?.message ||
                    error?.message ||
                    _t("The payment could not be saved. Nothing was recorded."),
            });
        }
    },
});
