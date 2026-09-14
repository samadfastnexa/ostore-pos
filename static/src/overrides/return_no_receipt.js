/** @odoo-module **/

import { patch } from "@web/core/utils/patch";
import { _t } from "@web/core/l10n/translation";
import { ControlButtons } from "@point_of_sale/app/screens/product_screen/control_buttons/control_buttons";
import { makeAwaitable } from "@point_of_sale/app/utils/make_awaitable_dialog";
import { ReturnNoReceiptPopup } from "./return_no_receipt_popup";
import { posRetailRequestManagerPin } from "../utils/manager_pin";

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

        const payload = await makeAwaitable(this.dialog, ReturnNoReceiptPopup, { order });
        if (!payload) {
            return;
        }

        order.is_refund = true;
        if (payload.unlinked) {
            order.pos_retail_return_unlinked = true;
        }
        if (payload.manager) {
            order.pos_retail_return_manager_id = payload.manager;
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

            if (line) {
                line.pos_retail_product_condition = returnLine.condition;
                line.pos_retail_return_pricing_policy = returnLine.policy;
                if (returnLine.reasonId) {
                    const r = this.pos.models["pos.retail.return.reason"].get(returnLine.reasonId);
                    if (r) {
                        order.return_reason_id = r;
                    }
                }
            }

            if (returnLine.originalOrderId && line) {
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
        // Straight to Payment screen, where Cash / Card / Customer Credit settle the refund
        this.pos.navigate("PaymentScreen", { orderUuid: order.uuid });
    },
});
