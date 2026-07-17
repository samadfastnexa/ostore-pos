/** @odoo-module **/

/* global Sha1 */

import { patch } from "@web/core/utils/patch";
import { _t } from "@web/core/l10n/translation";
import { useState } from "@odoo/owl";
import { PaymentScreen } from "@point_of_sale/app/screens/payment_screen/payment_screen";
import { NumberPopup } from "@point_of_sale/app/components/popups/number_popup/number_popup";
import { makeAwaitable } from "@point_of_sale/app/utils/make_awaitable_dialog";
import { accountTaxHelpers } from "@account/helpers/account_tax";

// Order-level discount, independent of pos_discount's own Product-Screen
// percentage button (left untouched). Reuses the exact same mechanism
// (a negative pos.order.line on config.discount_product_id, built via the
// shared tax-engine helper) so receipts/reports/rescale-on-cart-change all
// keep working unchanged -- this just adds a Fixed Amount mode, a role-based
// limit check, and manager-PIN approval on top.
patch(PaymentScreen.prototype, {
    setup() {
        super.setup(...arguments);
        this.orderDiscountState = useState({
            open: false,
            kind: "fixed",
            amount: "",
            reasonId: false,
            notes: "",
        });
    },

    // parseInt is a bare global, and OWL template expressions only resolve
    // identifiers on its RESERVED_WORDS whitelist (which excludes parseInt) or
    // the component context -- an inline parseInt() in the template compiles to
    // ctx['parseInt'](), i.e. undefined(), and throws "... is not a function"
    // when the reason dropdown changes. Do the parsing here in JS instead.
    posRetailSetReasonId(value) {
        this.orderDiscountState.reasonId = value ? parseInt(value) : false;
    },

    // Cart subtotal (excluding discount lines), used to convert a fixed
    // discount into an equivalent percentage for the native rescale-on-cart-
    // change watcher in posRetailApplyDiscountLines.
    posRetailComputeSubtotal(order) {
        return (order.lines || [])
            .filter((line) => !line.isDiscountLine)
            .reduce((sum, line) => sum + (line.price_subtotal_incl || 0), 0);
    },

    // --- role / limit -------------------------------------------------------
    posRetailGetCashierRole() {
        return this.pos.getCashier()?.pos_discount_role_id || false;
    },
    posRetailDiscountLimit(kind) {
        const role = this.posRetailGetCashierRole();
        if (role) {
            if (role.is_unlimited) {
                return Infinity;
            }
            return kind === "fixed" ? role.max_fixed_discount : role.max_percentage_discount;
        }
        return kind === "fixed"
            ? this.pos.config.pos_retail_max_fixed_discount
            : this.pos.config.pos_retail_max_percentage_discount;
    },

    // --- manager PIN approval ------------------------------------------------
    async posRetailCheckManagerPin() {
        const candidates = this.pos.models["hr.employee"].filter(
            (employee) => employee.pos_discount_role_id?.can_approve
        );
        if (!candidates.length) {
            this.notification.add(
                _t("No manager is configured to approve discounts."),
                { type: "danger" }
            );
            return false;
        }
        const inputPin = await makeAwaitable(this.dialog, NumberPopup, {
            formatDisplayedValue: (x) => x.replace(/./g, "•"),
            title: _t("Manager PIN"),
        });
        if (!inputPin) {
            return false;
        }
        const hashed = Sha1.hash(inputPin);
        const manager = candidates.find((employee) => employee._pin && employee._pin === hashed);
        if (!manager) {
            this.notification.add(_t("Incorrect manager PIN."), { type: "warning" });
            return false;
        }
        return manager;
    },

    // --- apply ----------------------------------------------------------------
    async posRetailApplyOrderDiscount() {
        const order = this.currentOrder;
        const state = this.orderDiscountState;
        const kind = state.kind;
        const amount = parseFloat(state.amount);

        if (!amount || amount <= 0) {
            this.notification.add(_t("Enter a discount amount first."), { type: "warning" });
            return;
        }
        if (kind === "percent" && amount > 100) {
            this.notification.add(_t("Percentage discount cannot exceed 100%."), { type: "warning" });
            return;
        }
        if (this.pos.config.pos_retail_require_discount_reason && !state.reasonId) {
            this.notification.add(_t("Please select a discount reason."), { type: "warning" });
            return;
        }

        let managerEmployee = false;
        const limit = this.posRetailDiscountLimit(kind);
        if (amount > limit) {
            if (!this.pos.config.pos_retail_require_manager_approval) {
                this.notification.add(
                    _t("Discount exceeds your allowed limit. Manager approval is required."),
                    { type: "danger" }
                );
                return;
            }
            this.notification.add(
                _t("Discount exceeds your allowed limit. Manager approval is required."),
                { type: "warning" }
            );
            managerEmployee = await this.posRetailCheckManagerPin();
            if (!managerEmployee) {
                return;
            }
            if (!this.pos.config.pos_retail_allow_manager_override) {
                const managerRole = managerEmployee.pos_discount_role_id;
                const managerLimit =
                    managerRole && !managerRole.is_unlimited
                        ? (kind === "fixed" ? managerRole.max_fixed_discount : managerRole.max_percentage_discount)
                        : Infinity;
                if (amount > managerLimit) {
                    this.notification.add(
                        _t("Amount exceeds the approving manager's own discount limit."),
                        { type: "danger" }
                    );
                    return;
                }
            }
        }

        order.discount_reason_id = state.reasonId
            ? this.pos.models["pos.retail.discount.reason"].get(state.reasonId)
            : false;
        order.discount_reason_notes = state.notes || "";
        order.discount_manager_id = managerEmployee || false;
        order.discount_input_type = kind;

        await this.posRetailApplyDiscountLines(kind, amount, order);
    },

    async posRetailApplyDiscountLines(kind, amount, order) {
        const taxKey = (taxIds) => taxIds.map((tax) => tax.id).sort((a, b) => a - b).join("_");
        const product = this.pos.config.discount_product_id;
        if (!product) {
            this.notification.add(
                _t(
                    "The discount product seems misconfigured. Make sure it is flagged as 'Can be Sold' and 'Available in Point of Sale'."
                ),
                { type: "danger" }
            );
            return;
        }

        const discountLinesMap = {};
        (order.discountLines || []).forEach((line) => {
            discountLinesMap[taxKey(line.tax_ids)] = line;
        });

        const lines = order.getOrderlines();
        const discountableLines = lines.filter((line) => line.isGlobalDiscountApplicable());
        const baseLines = discountableLines.map((line) =>
            accountTaxHelpers.prepare_base_line_for_taxes_computation(
                line,
                line.prepareBaseLineForTaxesComputationExtraValues()
            )
        );
        accountTaxHelpers.add_tax_details_in_base_lines(baseLines, order.company_id);
        accountTaxHelpers.round_base_lines_tax_details(baseLines, order.company_id);

        const groupingFunction = () => ({
            grouping_key: { product_id: product },
            raw_grouping_key: { product_id: product.id },
        });

        const globalDiscountBaseLines = accountTaxHelpers.prepare_global_discount_lines(
            baseLines,
            order.company_id,
            kind === "fixed" ? "fixed" : "percent",
            amount,
            { computation_key: "pos_retail_order_discount", grouping_function: groupingFunction }
        );

        // Store an equivalent percentage on the line so the native
        // rescale-on-cart-change watcher (keyed off order.globalDiscountPc,
        // patched by pos_discount) keeps this discount proportional too.
        const subtotal = this.posRetailComputeSubtotal(order);
        const percentForRescale =
            kind === "fixed" ? (subtotal ? (amount / subtotal) * 100 : 0) : amount;

        for (const baseLine of globalDiscountBaseLines) {
            const extra_tax_data = accountTaxHelpers.export_base_line_extra_tax_data(baseLine);
            extra_tax_data.discount_percentage = percentForRescale;

            const key = taxKey(baseLine.tax_ids);
            const existingLine = discountLinesMap[key];
            if (existingLine) {
                existingLine.extra_tax_data = extra_tax_data;
                existingLine.price_unit = baseLine.price_unit;
                delete discountLinesMap[key];
            } else {
                await this.pos.addLineToOrder(
                    {
                        product_id: baseLine.product_id,
                        price_unit: baseLine.price_unit,
                        qty: baseLine.quantity,
                        tax_ids: [["link", ...baseLine.tax_ids]],
                        product_tmpl_id: baseLine.product_id.product_tmpl_id,
                        extra_tax_data: extra_tax_data,
                    },
                    order,
                    { force: true },
                    false
                );
            }
        }

        Object.values(discountLinesMap).forEach((line) => line.delete());
    },
});
