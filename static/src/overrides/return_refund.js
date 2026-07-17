/** @odoo-module **/

import { patch } from "@web/core/utils/patch";
import { _t } from "@web/core/l10n/translation";
import { TicketScreen } from "@point_of_sale/app/screens/ticket_screen/ticket_screen";
import { SelectionPopup } from "@point_of_sale/app/components/popups/selection_popup/selection_popup";
import { makeAwaitable } from "@point_of_sale/app/utils/make_awaitable_dialog";

// Capture a return reason on the native "with receipt" refund flow. The core
// TicketScreen awaits addAdditionalRefundInfo(order, destinationOrder) right
// before sending the refund order to the PaymentScreen -- its own comment says
// this hook is meant for adding a refund reason. We prompt with the store's
// configured return reasons and store the choice on the refund order.
patch(TicketScreen.prototype, {
    async addAdditionalRefundInfo(order, destinationOrder) {
        await super.addAdditionalRefundInfo(...arguments);
        if (!this.pos.config.pos_retail_require_return_reason) {
            return;
        }
        const reasons = this.pos.models["pos.retail.return.reason"].getAll();
        if (!reasons.length) {
            return;
        }
        const selected = await makeAwaitable(this.dialog, SelectionPopup, {
            title: _t("Return Reason"),
            list: reasons.map((r) => ({ id: r.id, label: r.name, isSelected: false, item: r })),
        });
        if (selected) {
            destinationOrder.return_reason_id = selected;
        }
    },
});
