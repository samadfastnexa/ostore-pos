/** @odoo-module **/

import { patch } from "@web/core/utils/patch";
import { OpeningControlPopup } from "@point_of_sale/app/components/popups/opening_control_popup/opening_control_popup";

// Show who is opening the register on the Opening Control dialog.
//
// The session already records the user, but nothing on the dialog says so, and
// the opening float is the one figure in the day that is asserted rather than
// counted by the system. When the till is short at closing, the first question
// is who declared the opening cash, and a name on the screen at the moment it
// is typed is what makes that answerable without digging through the backend.
patch(OpeningControlPopup.prototype, {
    get posRetailCashierName() {
        // getCashier() and not pos.user: pos_hr overrides it to return the
        // logged-in EMPLOYEE, which is the person actually standing at the
        // till. Falling back to the user covers the case where employee logins
        // are not in use, and an empty string simply hides the line.
        return this.pos.getCashier?.()?.name || this.pos.user?.name || "";
    },
});
