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
    // Measurement-based selling. Same reasoning as onQtyStep: Orderline is
    // reused by the receipt and the customer display, so it gains data and
    // callbacks as optional props rather than any knowledge of the POS.
    posRetailUom: { type: String, optional: true },
    posRetailQuickQtys: { type: Array, optional: true },
    onQuickQty: { type: Function, optional: true },
};

// A product counted in Units needs no unit label: "3 Units" is noise where "3"
// is obvious. A product sold by the metre needs it on every line, because
// "12.50" and "12.50 m" are different claims and only one of them is true.
export function posRetailLineUom(line) {
    const template = line?.product_id?.product_tmpl_id;
    const name = line?.product_id?.uom_id?.name;
    if (!name || !template) {
        return "";
    }
    return template.pos_retail_measurement_type === "piece" ? "" : name;
}

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

    posRetailUom(line) {
        return posRetailLineUom(line);
    },

    // Shortcut quantities for measured goods (0.5 / 1 / 2 / 5 / 10 m and so on),
    // configured per product on the product form.
    //
    // Only on the SELECTED line. A cart of fifteen lines each carrying five
    // chips is a wall of buttons, and the cashier is only ever adjusting the one
    // they just touched. Returning [] renders nothing at all.
    posRetailQuickQtys(line) {
        if (!line || line.combo_parent_id) {
            return [];
        }
        // Never on a refund. A refund line carries a negative quantity, and the
        // chips SET the quantity rather than adding to it, so tapping "5m" on a
        // returned length silently turned the refund into a fresh sale of five
        // metres -- no dialog, no warning, and the customer's money kept. The
        // +/- buttons already guard on qty > 0; this is the same rule, plus the
        // explicit link a refund line carries back to what it is refunding.
        if (line.refunded_orderline_id || line.getQuantity() <= 0) {
            return [];
        }
        if (this.currentOrder?.getSelectedOrderline()?.uuid !== line.uuid) {
            return [];
        }
        const template = line.product_id?.product_tmpl_id;
        const raw = template?.pos_retail_quick_qty;
        if (!raw) {
            return [];
        }
        const allowsFractions = Boolean(template.pos_retail_allow_decimal);
        return String(raw)
            .split(",")
            .map((part) => Number.parseFloat(part.trim()))
            // The server-side constraint already rejects junk and fractions on
            // whole-unit products, but this list also renders for records that
            // predate it, so filter rather than trust.
            .filter((value) => Number.isFinite(value) && value > 0)
            .filter((value) => allowsFractions || Number.isInteger(value))
            .slice(0, 6);
    },

    // Sets the quantity outright rather than adding to it: the buttons are read
    // as "sell 2 metres", not "add 2 more metres".
    posRetailSetQty(line, qty) {
        const target = line.combo_parent_id || line;
        const result = target.setQuantity(qty, Boolean(target.combo_line_ids?.length));
        if (result !== true) {
            this.dialog.add(AlertDialog, result);
        }
    },
});
