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
    // Step 1: Identify all employees who qualify as a manager/approver:
    //  a) Their POS Discount Role has can_approve = true, OR
    //  b) They have POS manager / admin rights in core Odoo (_role === 'manager' or _user_role === 'admin').
    const managerEmployees = employeeModel.filter(
        (employee) =>
            Boolean(employee.pos_discount_role_id?.can_approve) ||
            employee._role === "manager" ||
            employee._user_role === "admin"
    );
    if (!managerEmployees.length) {
        notification.add(
            options.noManagerMessage ||
                _t("No manager is configured. Please assign a Manager role to an employee in Employees > Settings."),
            { type: "danger" }
        );
        return false;
    }

    // Step 2: Candidates must have a PIN code configured to authenticate.
    const candidates = managerEmployees.filter((employee) => Boolean(employee._pin));
    if (!candidates.length) {
        const names = managerEmployees.map((e) => e.name).join(", ");
        notification.add(
            _t(
                "Manager(s) (%s) have no PIN code configured. Please set a PIN code under Employees > Settings > Attendance/Point of Sale.",
                names
            ),
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
