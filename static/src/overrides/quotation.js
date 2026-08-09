/** @odoo-module **/

import { patch } from "@web/core/utils/patch";
import { _t } from "@web/core/l10n/translation";
import { ControlButtons } from "@point_of_sale/app/screens/product_screen/control_buttons/control_buttons";
import { NumberPopup } from "@point_of_sale/app/components/popups/number_popup/number_popup";
import { makeAwaitable } from "@point_of_sale/app/utils/make_awaitable_dialog";
import { PosRetailQuotationPicker } from "@pos_retail/overrides/quotation_picker";

// Quotations from the till: turn the current POS cart into a Sales quotation
// (sale.order) instead of ringing it up. The quotation is later settled back
// into the POS for payment via pos_sale's native "Quotation" button.
//
// Four actions, because a quote has a life beyond being written once:
//   Save as Quotation -> hand it to the customer (state 'sent')
//   Save Draft        -> worked out but not issued yet (state 'draft')
//   Update Quote      -> the customer changed their mind; rewrite an existing one
//   Duplicate Quote   -> start from a quote already given, for a similar order
patch(ControlButtons.prototype, {
    /** Cart lines worth quoting, minus the order-discount bookkeeping lines. */
    posRetailQuotableLines() {
        const order = this.pos.getOrder();
        return (order?.getOrderlines() || []).filter(
            (line) => !line.isDiscountLine && line.getQuantity() > 0
        );
    },

    /** Build the server payload from the cart, or false if it cannot be built. */
    async posRetailBuildQuotationVals({ askValidity = true } = {}) {
        const order = this.pos.getOrder();
        const cartLines = this.posRetailQuotableLines();
        if (!cartLines.length) {
            this.notification.add(
                _t("Add at least one product before saving a quotation."),
                { type: "warning" }
            );
            return false;
        }

        // A quotation needs a customer.
        let partner = order.getPartner();
        if (!partner) {
            partner = await this.pos.selectPartner();
            if (!partner) {
                return false;
            }
        }

        // Optional validity (in days). Cancelling just leaves it to the
        // company default; a positive number sets an explicit validity date.
        let validityDate = false;
        if (askValidity) {
            const daysInput = await makeAwaitable(this.dialog, NumberPopup, {
                title: _t("Quotation validity (days) - optional"),
                startingValue: 0,
            });
            const days = parseInt(daysInput);
            if (days > 0) {
                const d = new Date();
                d.setDate(d.getDate() + days);
                validityDate = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(
                    2,
                    "0"
                )}-${String(d.getDate()).padStart(2, "0")}`;
            }
        }

        return {
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
    },

    /** The cart has become a quotation; start a clean order so it cannot be
     *  charged again at the till by accident. */
    posRetailClearCartAfterQuote() {
        const order = this.pos.getOrder();
        this.pos.addNewOrder();
        this.pos.removeOrder(order, false);
        this.props.close?.();
    },

    async posRetailSaveQuotation({ draft }) {
        const vals = await this.posRetailBuildQuotationVals();
        if (!vals) {
            return;
        }
        let result;
        try {
            result = await this.pos.data.call("sale.order", "_pos_retail_create_quotation", [
                { ...vals, draft },
            ]);
        } catch {
            // The server raises a readable UserError which POS surfaces as a
            // dialog; keep the cart intact so the cashier can retry.
            return;
        }
        this.notification.add(
            draft
                ? _t("Draft quotation %s saved.", result.name)
                : _t("Quotation %s saved for %s.", result.name, result.partner_name),
            { type: "success" }
        );
        this.posRetailClearCartAfterQuote();
    },

    async onClickSaveAsQuotation() {
        await this.posRetailSaveQuotation({ draft: false });
    },

    async onClickSaveQuotationDraft() {
        await this.posRetailSaveQuotation({ draft: true });
    },

    /** Ask which existing quotation to act on. */
    async posRetailPickQuotation(title) {
        const order = this.pos.getOrder();
        return await makeAwaitable(this.dialog, PosRetailQuotationPicker, {
            title,
            partner: order?.getPartner() || null,
        });
    },

    async onClickUpdateQuotation() {
        // Build the cart payload FIRST: if the cart is empty or has no
        // customer there is nothing to update with, and asking the cashier to
        // pick a quotation before telling them that wastes their time.
        const vals = await this.posRetailBuildQuotationVals();
        if (!vals) {
            return;
        }
        const quote = await this.posRetailPickQuotation(_t("Update which quotation?"));
        if (!quote) {
            return;
        }
        let result;
        try {
            result = await this.pos.data.call("sale.order", "_pos_retail_update_quotation", [
                quote.id,
                vals,
            ]);
        } catch {
            return;
        }
        this.notification.add(
            _t("Quotation %s updated with the current cart.", result.name),
            { type: "success" }
        );
        this.posRetailClearCartAfterQuote();
    },

    async onClickDuplicateQuotation() {
        const quote = await this.posRetailPickQuotation(_t("Duplicate which quotation?"));
        if (!quote) {
            return;
        }
        let result;
        try {
            result = await this.pos.data.call("sale.order", "_pos_retail_duplicate_quotation", [
                quote.id,
            ]);
        } catch {
            return;
        }
        // Duplicating copies a whole document server-side (delivery terms,
        // fiscal position, fields other modules added), so the cart is left
        // untouched rather than being replaced by an approximation of it.
        this.notification.add(
            _t("%s copied to %s as a draft.", quote.name, result.name),
            { type: "success" }
        );
    },
});
