/** @odoo-module **/

import { patch } from "@web/core/utils/patch";
import { Navbar } from "@point_of_sale/app/components/navbar/navbar";

patch(Navbar.prototype, {
    // A Refund button in the top bar, beside Register and Orders.
    //
    // Returns are frequent at this counter and the route to one had a trap in
    // the middle: the orders list opens on Active orders, a finished sale is
    // not among them, so the sale being returned appears to be missing until
    // someone thinks to change the filter to Paid.
    //
    // This lands on that filter directly. TicketScreen accepts a stateOverride
    // prop (ticket_screen.js: `Object.assign(this.state, this.props
    // .stateOverride || {})`) and pos.navigate passes its second argument
    // through as props, so the filter is set on the way in rather than by the
    // cashier afterwards.
    posRetailStartRefund() {
        this.pos.navigate("TicketScreen", {
            stateOverride: { filter: "SYNCED" },
        });
    },

    // Make "Register" mean the selling screen, always.
    //
    // Core's onClickRegister calls navigateToOrderScreen, which reads the
    // screen the order was LAST on (pos_store.js:226-228), and navigate()
    // stamps the current screen onto the order as you move (pos_store.js:
    // 213-214). So from the payment screen the order remembers "PaymentScreen"
    // and Register navigates straight back to it: the button does nothing at
    // all, in the one place a cashier most wants it. They have opened payment
    // by mistake, or the customer has changed their mind about an item, and
    // they want the product grid back.
    //
    // Back still exists and still means "the previous step". Register now
    // means "the products", which is what its label promises.
    onClickRegister() {
        const order = this.pos.getOrder() || this.pos.addNewOrder();
        this.pos.navigate("ProductScreen", { orderUuid: order.uuid });
    },
});
