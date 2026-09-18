/** @odoo-module **/

import { patch } from "@web/core/utils/patch";
import { LoginScreen } from "@point_of_sale/app/screens/login_screen/login_screen";

// Navigate back to the Admin Panel / Control Center cleanly.
//
// Previously, if module_pos_hr was enabled and !this.pos.login, it forcibly logged
// the user out to /web/session/logout. That destroyed the admin session.
// Instead, if the browser is already signed into a user account with backend access,
// we navigate directly back to /odoo with active branch scoping preserved.
patch(LoginScreen.prototype, {
    async clickBack() {
        const kioskUserId = this.pos.config.pos_retail_kiosk_user_id?.[0] || this.pos.config.pos_retail_kiosk_user_id;
        const isKiosk = kioskUserId && this.pos.user?.id === kioskUserId;
        if (isKiosk) {
            window.location.href = "/web/login";
            return;
        }
        if (typeof this.pos.redirectToBackend === "function") {
            this.pos.redirectToBackend();
            return;
        }
        const companyId =
            this.pos.company?.id ||
            this.pos.config?.company_id?.[0] ||
            this.pos.config?.company_id?.id ||
            this.pos.config?.company_id;
        const cidsParam = companyId ? `?cids=${companyId}` : "";
        window.location.href = `/odoo${cidsParam}`;
    },
});
