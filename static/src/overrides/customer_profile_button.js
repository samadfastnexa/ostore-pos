/** @odoo-module **/

import { patch } from "@web/core/utils/patch";
import { useService } from "@web/core/utils/hooks";
import { SelectPartnerButton } from "@point_of_sale/app/screens/product_screen/control_buttons/select_partner_button/select_partner_button";
import { PosRetailCustomerProfile } from "@pos_retail/overrides/customer_profile";

patch(SelectPartnerButton.prototype, {
    setup() {
        super.setup(...arguments);
        this.posRetailDialog = useService("dialog");
    },

    posRetailShowProfile() {
        if (!this.props.partner) {
            return;
        }
        this.posRetailDialog.add(PosRetailCustomerProfile, {
            partner: this.props.partner,
        });
    },
});
