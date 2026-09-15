/** @odoo-module **/

import { patch } from "@web/core/utils/patch";
import { _t } from "@web/core/l10n/translation";
import { Navbar } from "@point_of_sale/app/components/navbar/navbar";
import { makeAwaitable } from "@point_of_sale/app/utils/make_awaitable_dialog";
import { SelectionPopup } from "@point_of_sale/app/components/popups/selection_popup/selection_popup";
import { ReturnNoReceiptPopup } from "./return_no_receipt_popup";
import { posRetailRequestManagerPin } from "../utils/manager_pin";

patch(Navbar.prototype, {
    // A Refund button in the top bar, beside Register and Orders.
    //
    // Opens a selection: "Return With Receipt" goes to the paid-orders list
    // (the core Odoo flow), and "Return Without Receipt" opens our custom
    // popup directly — no digging through menus needed.
    async posRetailStartRefund() {
        const allowNoReceipt = this.pos.config.pos_retail_allow_no_receipt_return;

        if (!allowNoReceipt) {
            // No-receipt returns disabled — go straight to the orders list.
            this.pos.navigate("TicketScreen", {
                stateOverride: { filter: "SYNCED" },
            });
            return;
        }

        const choice = await makeAwaitable(this.dialog, SelectionPopup, {
            title: _t("Refund / Return"),
            list: [
                {
                    id: "with_receipt",
                    label: _t("Return WITH Receipt (select from past orders)"),
                    isSelected: false,
                    item: "with_receipt",
                },
                {
                    id: "no_receipt",
                    label: _t("Return WITHOUT Receipt (quick return)"),
                    isSelected: false,
                    item: "no_receipt",
                },
            ],
        });

        if (!choice) {
            return;
        }

        if (choice === "with_receipt") {
            this.pos.navigate("TicketScreen", {
                stateOverride: { filter: "SYNCED" },
            });
            return;
        }

        // "no_receipt" — open the custom popup
        let order = this.pos.getOrder();
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

        this.pos.navigate("PaymentScreen", { orderUuid: order.uuid });
    },

    // Make "Register" mean the selling screen, always.
    onClickRegister() {
        const order = this.pos.getOrder() || this.pos.addNewOrder();
        this.pos.navigate("ProductScreen", { orderUuid: order.uuid });
    },
});

