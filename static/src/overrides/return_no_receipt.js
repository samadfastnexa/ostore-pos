/** @odoo-module **/

import { patch } from "@web/core/utils/patch";
import { _t } from "@web/core/l10n/translation";
import { ControlButtons } from "@point_of_sale/app/screens/product_screen/control_buttons/control_buttons";
import { SelectionPopup } from "@point_of_sale/app/components/popups/selection_popup/selection_popup";
import { makeAwaitable } from "@point_of_sale/app/utils/make_awaitable_dialog";
import { ReturnNoReceiptPopup } from "./return_no_receipt_popup";
import { posRetailRequestManagerPin } from "../utils/manager_pin";

// "Return (No Receipt)" flow: manager PIN -> return reason -> products/qty/price
// (+ optional customer, + optional link to an original sale) -> negative
// lines on a fresh is_refund order -> straight to Payment, where Cash, Card or
// Customer Credit stands in for "how should we handle the refund" -- the shop
// asked for that choice and core's own payment buttons already are it, so
// nothing new was built to duplicate them.
//
// Reuses the same manager-PIN challenge as the order-discount approval
// (employees whose discount role can_approve), via the shared helper in
// utils/manager_pin.js.
patch(ControlButtons.prototype, {
    async posRetailCheckReturnManagerPin() {
        return posRetailRequestManagerPin(this.pos, this.dialog, this.notification, {
            noManagerMessage: _t("No manager is configured to approve returns."),
        });
    },

    async onClickReturnNoReceipt() {
        let order = this.pos.getOrder();
        // Don't convert an in-progress sale into a return; start a fresh order.
        if (order && !order.is_refund && !order.isEmpty()) {
            order = this.pos.addNewOrder();
        }
        const isNewReturn = !order.is_refund;

        if (isNewReturn && this.pos.config.pos_retail_return_requires_manager) {
            // The employee record itself, not a plain yes/no -- discarding it
            // here is exactly what left every no-receipt return with no
            // record of who approved it, so a receipt asking "Authorized By"
            // had nothing to show.
            const manager = await this.posRetailCheckReturnManagerPin();
            if (!manager) {
                return;
            }
            order.pos_retail_return_manager_id = manager;
        }
        if (isNewReturn && this.pos.config.pos_retail_require_return_reason) {
            const reasons = this.pos.models["pos.retail.return.reason"].getAll();
            if (reasons.length) {
                const reason = await makeAwaitable(this.dialog, SelectionPopup, {
                    title: _t("Return Reason"),
                    list: reasons.map((r) => ({
                        id: r.id,
                        label: r.name,
                        isSelected: false,
                        item: r,
                    })),
                });
                if (!reason) {
                    return;
                }
                order.return_reason_id = reason;
            }
        }

        const payload = await makeAwaitable(this.dialog, ReturnNoReceiptPopup, { order });
        if (!payload) {
            return;
        }

        order.is_refund = true;
        // Marked the moment it is known, not guessed at later from whether a
        // link happens to be present: a return can fail to link for reasons
        // that have nothing to do with the cashier's choice (a typo, an order
        // that predates this database), and only the popup that actually
        // tried knows whether skipping the lookup was deliberate.
        if (payload.unlinked) {
            order.pos_retail_return_unlinked = true;
        }

        for (const returnLine of payload.lines) {
            const line = await this.pos.addLineToOrder(
                {
                    product_id: returnLine.product.id,
                    product_tmpl_id: returnLine.product.product_tmpl_id,
                    qty: -Math.abs(returnLine.qty),
                    price_unit: returnLine.price,
                    price_type: "manual",
                },
                order,
                { force: true },
                false
            );

            if (returnLine.originalOrderId && line) {
                // Use core's own link so linked quick returns share the same
                // cumulative-quantity constraint and reporting as receipt returns.
                const originalOrder = this.pos.models["pos.order"].get(returnLine.originalOrderId);
                const originalLine = originalOrder?.lines.find(
                    (candidate) => candidate.id === returnLine.originalOrderLineId
                );
                if (originalLine) {
                    line.refunded_orderline_id = originalLine;
                }
            }
        }

        this.props.close?.();
        // Straight to the till's own choice of how to give the money back,
        // rather than leaving the cashier to find Payment themselves. That
        // screen's Cash / Card / Customer Credit buttons ARE the refund
        // options: Customer Credit both credits the ledger and nets against
        // whatever the customer already owed, since it is the same account.
        this.pos.navigate("PaymentScreen", { orderUuid: order.uuid });
    },
});
