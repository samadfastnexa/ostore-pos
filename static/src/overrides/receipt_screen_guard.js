/** @odoo-module **/

import { patch } from "@web/core/utils/patch";
import { ReceiptScreen } from "@point_of_sale/app/screens/receipt_screen/receipt_screen";

// Reloading a receipt URL took the whole POS down with a blank screen.
//
// The POS only loads DRAFT orders at start-up (pos_order.py _load_pos_data_domain),
// so a finalised sale is never in memory after a refresh. Core notices this --
// useRouterParamsChecker() looks the order up and calls navigate() to bounce the
// user back -- but navigating does not abort the setup already in progress, and
// the next line of ReceiptScreen.setup() is:
//
//     const partner = this.currentOrder.getPartner();
//
// With no order that reads getPartner off undefined, which throws inside the Owl
// lifecycle and renders nothing at all. The user is left on a blank page with no
// way back except retyping the URL.
//
// Returning the currently open order as a fallback keeps setup on its feet for
// the one frame before core's own navigate() lands, so the miss ends on the
// product screen instead of a dead page. It deliberately does NOT try to fetch
// the finalised order from the server: to reprint an old receipt the supported
// path is Orders -> select -> Print Receipt, which loads it properly.
patch(ReceiptScreen.prototype, {
    get currentOrder() {
        return (
            this.pos.models["pos.order"].getBy("uuid", this.props.orderUuid) ||
            this.pos.getOrder()
        );
    },
});
