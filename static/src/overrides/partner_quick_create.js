/** @odoo-module **/

import { patch } from "@web/core/utils/patch";
import { _t } from "@web/core/l10n/translation";
import { PartnerList } from "@point_of_sale/app/screens/partner_list/partner_list";

// Create a customer straight from what the cashier typed.
//
// Core's flow is: type -> press Create -> a full contact form opens -> fill it
// -> save -> pick the customer from the list. At a till that is far too slow,
// and the only thing usually known is a name or a phone number. This adds a
// one-tap row to the search results that creates the customer from the search
// text itself and immediately attaches it to the order.
//
// The full Create button is left in place for when a real contact record with
// an address is wanted.
patch(PartnerList.prototype, {
    setup() {
        super.setup(...arguments);
        this.state.posRetailCreating = false;
    },

    get posRetailTypedName() {
        return (this.state.query || "").trim();
    },

    get posRetailCanQuickCreate() {
        return Boolean(this.posRetailTypedName) && this.pos.cashier._role !== "minimal";
    },

    // Mostly digits means the cashier typed a phone number, so store it in the
    // phone field too rather than leaving a customer whose name is a number and
    // whose phone is empty.
    get posRetailTypedIsPhone() {
        const stripped = this.posRetailTypedName.replace(/[+\s()\-.]/g, "");
        return /^\d{4,}$/.test(stripped);
    },

    async posRetailQuickCreate() {
        const typed = this.posRetailTypedName;
        if (!typed || this.state.posRetailCreating) {
            return;
        }
        this.state.posRetailCreating = true;
        try {
            const values = this.posRetailTypedIsPhone
                ? { name: typed, phone: typed }
                : { name: typed };
            const result = await this.pos.data.create("res.partner", [values]);
            const created = Array.isArray(result) ? result[0] : result;
            const partner = this.pos.models["res.partner"].get(created?.id) || created;
            if (!partner?.id) {
                this.notification.add(_t("Could not create the customer."), { type: "danger" });
                return;
            }
            this.notification.add(_t('Customer "%s" added.', typed), { type: "success" });
            this.clickPartner(partner);
        } finally {
            this.state.posRetailCreating = false;
        }
    },
});
