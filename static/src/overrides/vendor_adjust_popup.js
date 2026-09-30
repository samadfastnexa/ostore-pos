/** @odoo-module **/

import { Component, useState } from "@odoo/owl";
import { Dialog } from "@web/core/dialog/dialog";
import { _t } from "@web/core/l10n/translation";
import { usePos } from "@point_of_sale/app/hooks/pos_hook";
import { useService } from "@web/core/utils/hooks";

/**
 * Interactive POS Dialog for adjusting a vendor's khata balance.
 * Supports:
 * - "Shop Owes LESS" (Vendor discount, volume rebate, damaged goods return, waiver)
 * - "Shop Owes MORE" (Old debt carried forward, unbilled delivery, debit note)
 */
export class PosRetailVendorAdjustPopup extends Component {
    static template = "pos_retail.VendorAdjustPopup";
    static components = { Dialog };
    static props = {
        close: Function,
        vendor: Object,
        onAdjustDone: { type: Function, optional: true },
    };

    setup() {
        this.parseFloat = parseFloat;
        this.pos = usePos();
        this.notification = useService("notification");

        const vendor = this.props.vendor;
        const todayStr = new Date().toISOString().split("T")[0];

        this.state = useState({
            direction: (vendor.balance || 0) > 0 ? "decrease" : "increase",
            amount: "",
            reason: "",
            date: todayStr,
            submitting: false,
            errorMsg: "",
        });
    }

    get vendor() {
        return this.props.vendor;
    }

    get previousBalance() {
        return this.vendor.balance || 0;
    }

    get newBalancePreview() {
        const amt = parseFloat(this.state.amount) || 0;
        if (this.state.direction === "increase") {
            return this.previousBalance + amt;
        } else {
            return this.previousBalance - amt;
        }
    }

    get canConfirm() {
        if (this.state.submitting) return false;
        const val = parseFloat(this.state.amount);
        return !isNaN(val) && val > 0 && Boolean((this.state.reason || "").trim());
    }

    formatCurrency(amount) {
        const val = typeof amount === "number" ? amount : parseFloat(amount) || 0;
        if (this.env?.utils?.formatCurrency) {
            return this.env.utils.formatCurrency(val);
        }
        return val.toFixed(2);
    }

    setDirection(dir) {
        this.state.direction = dir;
    }

    setQuickReason(r) {
        this.state.reason = r;
    }

    async onConfirm() {
        const amount = parseFloat(this.state.amount);
        if (!amount || amount <= 0) {
            this.state.errorMsg = _t("Please enter an amount greater than zero.");
            return;
        }

        const reason = (this.state.reason || "").trim();
        if (!reason) {
            this.state.errorMsg = _t("Please enter a reason for the khata adjustment.");
            return;
        }

        this.state.submitting = true;
        this.state.errorMsg = "";
        try {
            const cashier = this.pos.getCashier();
            const result = await this.pos.data.call(
                "res.partner",
                "pos_retail_adjust_vendor_khata",
                [
                    this.vendor.id,
                    amount,
                    this.state.direction,
                    reason,
                    this.pos.config.id,
                    cashier?.id || false,
                    this.state.date,
                ]
            );

            // Update vendor in local view
            this.vendor.balance = result.new_balance;
            this.vendor.balance_formatted = result.new_balance_formatted;

            this.notification.add(
                _t("Vendor Khata adjusted (%(dir)s %(amt)s). New balance: %(bal)s", {
                    dir: result.direction_label,
                    amt: result.amount_formatted,
                    bal: result.new_balance_formatted,
                }),
                { type: "success" }
            );

            if (typeof this.props.onAdjustDone === "function") {
                this.props.onAdjustDone(result);
            }
            this.props.close();
        } catch (error) {
            this.state.errorMsg =
                error?.data?.message ||
                error?.message ||
                _t("Khata adjustment could not be saved.");
        } finally {
            this.state.submitting = false;
        }
    }
}
