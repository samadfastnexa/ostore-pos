import { PosStore } from "@point_of_sale/app/services/pos_store";
import { patch } from "@web/core/utils/patch";

patch(PosStore.prototype, {
    // Core calls this whenever a new order is created without an explicit
    // partner (pos_store.js createNewOrder / getEmptyOrder) and returns null;
    // returning the configured partner's id pre-selects it, exactly the way
    // l10n_ar_pos pre-selects its "Consumidor Final". The value may arrive as
    // a linked record or, if the partner somehow wasn't preloaded, a raw id.
    getDefaultPartnerId() {
        const partner = this.config.pos_retail_default_partner_id;
        if (partner) {
            return typeof partner === "number" ? partner : partner.id;
        }
        return super.getDefaultPartnerId();
    },
});
