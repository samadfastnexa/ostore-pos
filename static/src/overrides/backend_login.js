/** @odoo-module **/

import { patch } from "@web/core/utils/patch";
import { LoginScreen } from "@point_of_sale/app/screens/login_screen/login_screen";

// pos_hr's own "Back to Backend" requires selecting a cashier whose employee
// record happens to be linked to the currently authenticated web user -- if
// no employee is linked to that particular login (or the wrong one is
// picked), it fails with "Only the cashier linked to the logged-in user
// (X) can proceed to the Backend." and, worse, first pops up a list of every
// employee just to find out. For an admin managing multiple backend logins,
// re-authenticating with real credentials is both simpler and safer than
// trusting whichever web session happens to be cached in the terminal's
// browser. Log out and land on the real Odoo login page instead -- same
// route (/web/session/logout) as the standard "Log out" menu item.
patch(LoginScreen.prototype, {
    async clickBack() {
        if (this.pos.config.module_pos_hr && !this.pos.login) {
            window.location.href = "/web/session/logout";
            return;
        }
        return super.clickBack();
    },
});
