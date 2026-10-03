/** @odoo-module **/

import { patch } from "@web/core/utils/patch";
import { LoginScreen } from "@point_of_sale/app/screens/login_screen/login_screen";

// Navigate to Admin Panel / Login from the till lock screen.
//
// When the cashier closes or locks the register, clicking "Admin Panel / Control Center"
// should cleanly log out the cashier's till session and redirect to the backend login page
// (/web/session/logout?redirect=/web/login) so the administrator can enter their credentials
// and securely log into the Admin Panel.
patch(LoginScreen.prototype, {
    async clickBack() {
        // If currently in PIN entry mode (button says "Discard"), simply cancel PIN mode.
        if (this.pos?.login && this.pos?.config?.module_pos_hr) {
            this.state.pin = "";
            this.pos.login = false;
            return;
        }

        // Redirect to login page for the administrator, logging out any active cashier session.
        window.location.href = "/web/session/logout?redirect=/web/login";
    },
});
