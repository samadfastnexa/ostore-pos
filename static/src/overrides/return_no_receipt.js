/** @odoo-module **/

import { patch } from "@web/core/utils/patch";
import { _t } from "@web/core/l10n/translation";
import { ControlButtons } from "@point_of_sale/app/screens/product_screen/control_buttons/control_buttons";
import { SelectionPopup } from "@point_of_sale/app/components/popups/selection_popup/selection_popup";
import { makeAwaitable } from "@point_of_sale/app/utils/make_awaitable_dialog";
import { ReturnNoReceiptPopup } from "./return_no_receipt_popup";
import { posRetailRequestManagerPin } from "../utils/manager_pin";

// "Return (No Receipt)" flow: manager PIN -> return reason -> product/qty/price
// popup -> add a negative-qty line to a fresh is_refund order. Checkout then
// refunds it and restocks inventory natively. Reuses the same manager-PIN
// challenge as the order-discount approval (employees whose discount role
// can_approve), via the shared helper in utils/manager_pin.js.
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
            if (!(await this.posRetailCheckReturnManagerPin())) {
                return;
            }
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

        const payload = await makeAwaitable(this.dialog, ReturnNoReceiptPopup, {});
        if (!payload) {
            return;
        }

        order.is_refund = true;
        await this.pos.addLineToOrder(
            {
                product_id: payload.product,
                product_tmpl_id: payload.product.product_tmpl_id,
                qty: -Math.abs(payload.qty),
                price_unit: payload.price,
                price_type: "manual",
            },
            order,
            { force: true },
            false
        );
        this.notification.add(
            _t("Return line added. Add more items or go to Payment to refund."),
            { type: "success" }
        );
        this.props.close?.();
    },
});
