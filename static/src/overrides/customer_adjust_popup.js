/** @odoo-module **/

import { Component, useState } from "@odoo/owl";
import { Dialog } from "@web/core/dialog/dialog";
import { _t } from "@web/core/l10n/translation";
import { usePos } from "@point_of_sale/app/hooks/pos_hook";
import { useService } from "@web/core/utils/hooks";

/**
 * Interactive POS Dialog for adjusting a customer's khata balance.
 * Supports:
 * - "Customer Owes LESS" (Discount, waiver, correction, return deduction)
 * - "Customer Owes MORE" (Old paper khata debt, unpaid goods, opening balance)
 * - "Set Exact Balance" (Target Balance: auto-computes difference & direction)
 */
export class PosRetailCustomerAdjustPopup extends Component {
    static template = "pos_retail.CustomerAdjustPopup";
    static components = { Dialog };
    static props = {
        close: Function,
        partner: Object,
        onAdjustDone: { type: Function, optional: true },
    };

    setup() {
        this.parseFloat = parseFloat;
        this.pos = usePos();
        this.notification = useService("notification");

        const todayStr = new Date().toISOString().split("T")[0];

        this.state = useState({
            mode: "relative", // "relative" or "target"
            direction: (this.previousBalance > 0) ? "decrease" : "increase",
            amount: "",
            targetBalance: "",
            reason: "",
            date: todayStr,
            submitting: false,
            errorMsg: "",
        });
    }

    get partner() {
        return this.props.partner || {};
    }

    get previousBalance() {
        if (typeof this.partner.balance === "number") {
            return this.partner.balance;
        }
        if (typeof this.partner.pos_outstanding_balance === "number") {
            return this.partner.pos_outstanding_balance;
        }
        if (typeof this.partner.credit === "number") {
            return this.partner.credit;
        }
        const val = parseFloat(this.partner.balance || this.partner.pos_outstanding_balance || this.partner.credit);
        return isNaN(val) ? 0 : val;
    }

    get previousBalanceFormatted() {
        if (this.partner.balance_formatted) {
            return this.partner.balance_formatted;
        }
        return this.formatCurrency(this.previousBalance);
    }

    get targetBalanceNum() {
        const val = parseFloat(this.state.targetBalance);
        return isNaN(val) ? 0 : val;
    }

    get computedAdjustmentAmount() {
        if (this.state.mode === "target") {
            return Math.abs(this.targetBalanceNum - this.previousBalance);
        }
        const val = parseFloat(this.state.amount);
        return isNaN(val) ? 0 : val;
    }

    get computedDirection() {
        if (this.state.mode === "target") {
            return this.targetBalanceNum >= this.previousBalance ? "increase" : "decrease";
        }
        return this.state.direction;
    }

    get newBalancePreview() {
        if (this.state.mode === "target") {
            return this.targetBalanceNum;
        }
        const amt = parseFloat(this.state.amount) || 0;
        if (this.state.direction === "increase") {
            return this.previousBalance + amt;
        } else {
            return this.previousBalance - amt;
        }
    }

    get canConfirm() {
        if (this.state.submitting) return false;
        const amt = this.computedAdjustmentAmount;
        return amt > 0.005 && Boolean((this.state.reason || "").trim());
    }

    formatCurrency(amount) {
        const val = typeof amount === "number" ? amount : parseFloat(amount) || 0;
        if (this.env?.utils?.formatCurrency) {
            return this.env.utils.formatCurrency(val);
        }
        return val.toFixed(2);
    }

    setMode(mode) {
        this.state.mode = mode;
        this.state.errorMsg = "";
    }

    setDirection(dir) {
        this.state.direction = dir;
    }

    setQuickReason(r) {
        this.state.reason = r;
    }

    async onConfirm() {
        const amount = this.computedAdjustmentAmount;
        if (!amount || amount <= 0.005) {
            this.state.errorMsg = this.state.mode === "target"
                ? _t("Target balance must be different from current balance.")
                : _t("Please enter an amount greater than zero.");
            return;
        }

        const reason = (this.state.reason || "").trim();
        if (!reason) {
            this.state.errorMsg = _t("Please enter a reason / note for the khata adjustment.");
            return;
        }

        const direction = this.computedDirection;

        this.state.submitting = true;
        this.state.errorMsg = "";
        try {
            const cashier = this.pos.getCashier();
            const result = await this.pos.data.call(
                "res.partner",
                "pos_retail_adjust_customer_khata",
                [
                    this.partner.id,
                    amount,
                    direction,
                    reason,
                    this.pos.config.id,
                    cashier?.id || false,
                    this.state.date,
                ]
            );

            // Update partner in local view
            this.partner.balance = result.new_balance;
            this.partner.pos_outstanding_balance = result.new_balance;
            this.partner.balance_formatted = result.new_balance_formatted;

            if (this.pos?.models?.["res.partner"]) {
                const loadedPartner = this.pos.models["res.partner"].get(this.partner.id);
                if (loadedPartner) {
                    loadedPartner.pos_outstanding_balance = result.new_balance;
                    loadedPartner.credit = result.new_balance;
                }
            }

            this.notification.add(
                _t("Customer Khata adjusted (%(dir)s %(amt)s). New balance: %(bal)s", {
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
                _t("Customer khata adjustment could not be saved.");
        } finally {
            this.state.submitting = false;
        }
    }
}
