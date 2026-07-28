/** @odoo-module **/

import { _t } from "@web/core/l10n/translation";
import { patch } from "@web/core/utils/patch";
import { PaymentScreen } from "@point_of_sale/app/screens/payment_screen/payment_screen";
import { AlertDialog, ConfirmationDialog } from "@web/core/confirmation_dialog/confirmation_dialog";
import { useService } from "@web/core/utils/hooks";
import { posRetailRequestManagerPin } from "@pos_retail/utils/manager_pin";

// Credit limit on Customer Account sales.
//
// Selling "on account" is the one payment method that sends a customer home
// owing money, so it is the one place a limit belongs. The check runs before
// the payment line is added: once a line exists the cashier has already
// committed the sale in their head, and refusing it then is worse UX than
// refusing it now.
//
// A cashier cannot wave the limit away, but a manager can, with the same PIN
// challenge already used for discounts and price overrides. Who approved it
// is written onto the order so the decision is not anonymous.
patch(PaymentScreen.prototype, {
    setup() {
        super.setup(...arguments);
        this.posRetailNotification = useService("notification");
    },

    async addNewPaymentLine(paymentMethod) {
        if (!(await this.posRetailCheckCreditLimit(paymentMethod))) {
            return false;
        }
        return super.addNewPaymentLine(...arguments);
    },

    /**
     * @returns true when the sale may proceed (within limit, no limit set,
     * not an account sale, or a manager approved it).
     */
    async posRetailCheckCreditLimit(paymentMethod) {
        if (paymentMethod?.type !== "pay_later") {
            return true;
        }
        const order = this.currentOrder;
        const partner = order.getPartner();
        if (!partner) {
            // Core already refuses an account payment without a customer;
            // leave that message to it rather than showing two.
            return true;
        }
        const limit = partner.pos_credit_limit || 0;
        if (limit <= 0) {
            return true;
        }

        // What this sale would add to their debt: the part still unpaid.
        const due = Math.max(order.getDue(), 0);
        const balance = partner.pos_outstanding_balance || 0;
        const projected = balance + due;
        if (projected <= limit) {
            return true;
        }

        const over = projected - limit;
        const fmt = (v) => this.env.utils.formatCurrency(v);
        const approved = await new Promise((resolve) => {
            this.dialog.add(ConfirmationDialog, {
                title: _t("Over Credit Limit"),
                body: _t(
                    "%(name)s already owes %(balance)s and this sale would take them to " +
                        "%(projected)s, which is %(over)s past their %(limit)s limit.\n\n" +
                        "A manager can approve this sale.",
                    {
                        name: partner.name,
                        balance: fmt(balance),
                        projected: fmt(projected),
                        over: fmt(over),
                        limit: fmt(limit),
                    }
                ),
                confirmLabel: _t("Manager Approval"),
                cancelLabel: _t("Cancel"),
                confirm: () => resolve(true),
                cancel: () => resolve(false),
            });
        });
        if (!approved) {
            return false;
        }

        const manager = await posRetailRequestManagerPin(
            this.pos,
            this.dialog,
            this.posRetailNotification,
            {
                title: _t("Manager PIN to allow credit"),
                noManagerMessage: _t(
                    "No manager is set up to approve credit. Set one under " +
                        "Point of Sale, Configuration, Discount Roles."
                ),
            }
        );
        if (!manager) {
            return false;
        }

        // Snapshot the figures the manager actually approved against: the
        // customer's balance moves on, and an audit trail that recomputes it
        // later would show numbers nobody ever saw.
        order.pos_retail_credit_manager_id = manager;
        order.pos_retail_credit_over_amount = over;
        order.pos_retail_credit_before = balance;
        order.pos_retail_credit_after = projected;
        order.pos_retail_credit_limit = limit;
        this.posRetailNotification.add(
            _t("Credit approved by %s", manager.name),
            { type: "success" }
        );
        return true;
    },
});
