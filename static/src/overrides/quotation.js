/** @odoo-module **/

import { patch } from "@web/core/utils/patch";
import { _t } from "@web/core/l10n/translation";
import { ControlButtons } from "@point_of_sale/app/screens/product_screen/control_buttons/control_buttons";
import { NumberPopup } from "@point_of_sale/app/components/popups/number_popup/number_popup";
import { makeAwaitable } from "@point_of_sale/app/utils/make_awaitable_dialog";

// "Save as Quotation": turn the current POS cart into a draft Sales quotation
// (sale.order) instead of ringing it up. The quotation is later settled back
// into the POS for payment via pos_sale's native "Quotation" button
// (Convert to Sale). Requires a customer (prompted if none). Validity is
// optional -- left blank, sale.order applies the company's default validity.
patch(ControlButtons.prototype, {
    async onClickSaveAsQuotation() {
        const order = this.pos.getOrder();
        // Only real sellable lines -- skip the order-discount product lines.
        const cartLines = (order?.getOrderlines() || []).filter(
            (line) => !line.isDiscountLine && line.getQuantity() > 0
        );
        if (!cartLines.length) {
            this.notification.add(
                _t("Add at least one product before saving a quotation."),
                { type: "warning" }
            );
            return;
        }

        // A quotation needs a customer.
        let partner = order.getPartner();
        if (!partner) {
            partner = await this.pos.selectPartner();
            if (!partner) {
                return;
            }
        }

        // Optional validity (in days). Cancelling just leaves it to the
        // company default; a positive number sets an explicit validity date.
        let validityDate = false;
        const daysInput = await makeAwaitable(this.dialog, NumberPopup, {
            title: _t("Quotation validity (days) - optional"),
            startingValue: 0,
        });
        const days = parseInt(daysInput);
        if (days > 0) {
            const d = new Date();
            d.setDate(d.getDate() + days);
            validityDate = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(
                d.getDate()
            ).padStart(2, "0")}`;
        }

        const vals = {
            partner_id: partner.id,
            validity_date: validityDate,
            lines: cartLines.map((line) => ({
                product_id: line.product_id.id,
                qty: line.getQuantity(),
                price_unit: line.price_unit,
                discount: line.discount || 0,
                tax_ids: (line.tax_ids || []).map((tax) => tax.id),
            })),
        };

        let result;
        try {
            result = await this.pos.data.call("sale.order", "_pos_retail_create_quotation", [vals]);
        } catch {
            // The server raises a readable UserError which POS surfaces as a
            // dialog; keep the cart intact so the cashier can retry.
            return;
        }

        this.notification.add(
            _t("Quotation %s saved for %s.", result.name, partner.name),
            { type: "success" }
        );

        // The cart is now captured as a quotation -- start a clean order so it
        // can't be accidentally charged again at the till.
        this.pos.addNewOrder();
        this.pos.removeOrder(order, false);
        this.props.close?.();
    },
});
