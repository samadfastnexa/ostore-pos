/** @odoo-module **/

import { patch } from "@web/core/utils/patch";
import { PosStore } from "@point_of_sale/app/services/pos_store";

// Clean and reliable navigation back to the Odoo backend admin interface.
//
// Core's redirectToBackend() hardcodes "/odoo/action-point_of_sale.action_client_pos_menu".
// That client action lacks company/branch scoping params (cids), resetting the active
// branch/company to default, and fails if the user or cashier does not have access
// to the root POS menu action.
//
// Routing to `/odoo?cids=${companyId}` cleanly preserves the active branch and company
// scoping, respects user permissions, and opens the standard backend workspace.
patch(PosStore.prototype, {
    redirectToBackend() {
        const companyId =
            this.company?.id ||
            this.config?.company_id?.[0] ||
            this.config?.company_id?.id ||
            this.config?.company_id;
        const cidsParam = companyId ? `?cids=${companyId}` : "";
        window.location.href = `/odoo${cidsParam}`;
    },
});
