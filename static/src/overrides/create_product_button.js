/** @odoo-module **/

import { patch } from "@web/core/utils/patch";
import { user } from "@web/core/user";
import { useState, onWillStart } from "@odoo/owl";
import { PosStore } from "@point_of_sale/app/services/pos_store";
import { ControlButtons } from "@point_of_sale/app/screens/product_screen/control_buttons/control_buttons";

// Let the shop's own permission decide who may add a product at the till.
//
// pos_hr allows product creation only for employeeIsAdmin -- a cashier the
// REGISTER lists under Advanced Employees. That made adding a line to the
// catalogue and administering a till the same privilege, so the only way to
// let a cashier create a product was to hand them the office as well.
//
// Core's own check is kept and re-run rather than skipped: it asks whether
// the signed-in ACCOUNT can create a product, which is a different question
// from whether this PERSON is allowed to. A till is one shared login, so the
// second does not imply the first, and a button that fails on save is how a
// cashier ends up reading an access error aloud to a customer.
patch(PosStore.prototype, {
    async allowProductCreation() {
        if (this.config.module_pos_hr && this.getCashier()?._can_create_product) {
            return await user.checkAccessRight("product.product", "create");
        }
        return await super.allowProductCreation(...arguments);
    },
});

// "New Product" in the Actions dialog.
//
// Core puts it in the burger menu, where a shopkeeper looks for settings
// rather than for something to do mid-sale. This shop asked for every action
// a cashier performs to be in one place, for a good reason: the counter is
// busy, the customer is waiting, and someone who is not technical should not
// be hunting through two menus to find it.
patch(ControlButtons.prototype, {
    setup() {
        super.setup(...arguments);
        // Resolved once when the dialog is built rather than on every render:
        // the access check is a server round trip, and a getter that fires it
        // repeatedly would put a request behind every keystroke in the cart.
        this.posRetailProduct = useState({ canCreate: false });
        onWillStart(async () => {
            this.posRetailProduct.canCreate = await this.pos.allowProductCreation();
        });
    },

    onClickCreateProduct() {
        // Core's own flow, deliberately: it opens the full product form, so a
        // product added at the counter carries the same cost, category and
        // brand as one added in the office. A cut-down popup here would create
        // half-finished records for somebody to find and repair later.
        this.pos.editProduct();
    },
});
