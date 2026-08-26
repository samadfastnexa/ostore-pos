/** @odoo-module **/

/* global Sha1 */

import { _t } from "@web/core/l10n/translation";
import { NumberPopup } from "@point_of_sale/app/components/popups/number_popup/number_popup";
import { makeAwaitable } from "@point_of_sale/app/utils/make_awaitable_dialog";

/**
 * Shared manager-PIN challenge, used by order discounts, no-receipt returns and
 * price overrides. Candidates are employees whose POS Discount Role can approve.
 *
 * The server only ever sends the SHA-1 digest of a PIN (pos_hr
 * get_barcodes_and_pin_hashed), so the comparison is digest against digest and
 * the plaintext never leaves the popup.
 *
 * @returns the approving hr.employee record, or false if cancelled/incorrect.
 */
export async function posRetailRequestManagerPin(pos, dialog, notification, options = {}) {
    // hr.employee is only loaded into the POS when the register has Cashier
    // Log-in (module_pos_hr) enabled; without it there is nobody to approve,
    // so refuse cleanly instead of crashing on a missing model.
    const employeeModel = pos.models["hr.employee"];
    if (!employeeModel) {
        notification.add(
            _t(
                "Manager approval needs cashier log-in: enable 'Log in with Employees' on this register in the POS settings."
            ),
            { type: "danger" }
        );
        return false;
    }
    const candidates = employeeModel.filter(
        (employee) => employee.pos_discount_role_id?.can_approve
    );
    if (!candidates.length) {
        notification.add(
            options.noManagerMessage || _t("No manager is configured to give approval."),
            { type: "danger" }
        );
        return false;
    }
    const inputPin = await makeAwaitable(dialog, NumberPopup, {
        formatDisplayedValue: (x) => x.replace(/./g, "•"),
        title: options.title || _t("Manager PIN"),
    });
    if (!inputPin) {
        return false;
    }
    const hashed = Sha1.hash(inputPin);
    const manager = candidates.find((employee) => employee._pin && employee._pin === hashed);
    if (!manager) {
        notification.add(_t("Incorrect manager PIN."), { type: "warning" });
        return false;
    }
    return manager;
}
