/** @odoo-module **/

import { patch } from "@web/core/utils/patch";
import { Orderline } from "@point_of_sale/app/components/orderline/orderline";
import { OrderSummary } from "@point_of_sale/app/screens/product_screen/order_summary/order_summary";
import { AlertDialog } from "@web/core/confirmation_dialog/confirmation_dialog";

// Per-line quantity buttons in the cart.
//
// Orderline is a generic presentational component reused by the receipt and the
// customer display, neither of which has the pos/dialog services. So instead of
// giving Orderline any logic, it just gains an optional callback prop: only the
// product-screen cart (OrderSummary) passes it, so the buttons render there and
// nowhere else.
Orderline.props = {
    ...Orderline.props,
    onQtyStep: { type: Function, optional: true },
};

patch(OrderSummary.prototype, {
    // Mirrors the native numpad quantity path (OrderSummary._setValue):
    // a combo child is driven from its parent, setQuantity returns true or an
    // error payload to surface, and reaching zero removes the line the same way
    // the numpad's backspace does.
    posRetailQtyStep(line, delta) {
        let target = line;
        if (target.combo_parent_id) {
            target = target.combo_parent_id;
        }
        const newQty = target.getQuantity() + delta;
        if (newQty <= 0) {
            this.currentOrder.removeOrderline(target);
            return;
        }
        const result = target.setQuantity(newQty, Boolean(target.combo_line_ids?.length));
        if (result !== true) {
            this.dialog.add(AlertDialog, result);
        }
    },
});
