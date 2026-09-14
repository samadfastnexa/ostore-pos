/** @odoo-module **/

import { Component, onWillStart, useState } from "@odoo/owl";
import { Dialog } from "@web/core/dialog/dialog";
import { _t } from "@web/core/l10n/translation";
import { usePos } from "@point_of_sale/app/hooks/pos_hook";
import { useService } from "@web/core/utils/hooks";

/**
 * Interactive POS Dialog for receiving customer khata payments.
 * Implements Requirements 1, 2, 3, 4, and 5:
 * - Select Amount, Payment Method (Cash, Bank, Card, etc.), Date, Reference/Notes
 * - Visible Live FIFO Allocation Preview Table before confirmation
 * - Automatic deterministic oldest-debt-first allocation
 */
export class ReceivePaymentPopup extends Component {
    static template = "pos_retail.ReceivePaymentPopup";
    static components = { Dialog };
    static props = {
        close: Function,
        getPayload: Function,
        partner: Object,
    };

    setup() {
        this.pos = usePos();
        this.dialog = useService("dialog");
        this.notification = useService("notification");

        const partner = this.props.partner;
        const initialOwed = partner.pos_outstanding_balance || 0;
        const todayStr = new Date().toISOString().split("T")[0];

        this.state = useState({
            amount: initialOwed > 0 ? String(initialOwed) : "",
            journals: [],
            journalId: false,
            date: todayStr,
            memo: "",
            allocations: [],
            previousTotal: initialOwed,
            previousTotalFormatted: this.formatCurrency(initialOwed),
            newTotal: 0,
            newTotalFormatted: this.formatCurrency(0),
            unallocated: 0,
            unallocatedFormatted: this.formatCurrency(0),
            loadingAllocations: false,
            submitting: false,
            errorMsg: "",
        });

        onWillStart(async () => {
            await this.loadJournals();
            if (parseFloat(this.state.amount) > 0) {
                await this.refreshAllocation(parseFloat(this.state.amount));
            }
        });
    }

    get partner() {
        return this.props.partner;
    }

    formatCurrency(amount) {
        if (this.env?.utils?.formatCurrency) {
            return this.env.utils.formatCurrency(amount || 0);
        }
        return (amount || 0).toFixed(2);
    }

    async loadJournals() {
        try {
            const partnerCompanyId = this.partner.company_id?.id || false;
            const journals = await this.pos.data.call(
                "pos.retail.khata.payment",
                "get_pos_payment_journals",
                [partnerCompanyId]
            );
            if (journals && journals.length) {
                this.state.journals = journals;
                const defaultCash = journals.find((j) => j.is_cash) || journals[0];
                this.state.journalId = defaultCash ? defaultCash.id : journals[0].id;
                return;
            }
        } catch (err) {
            console.warn("PosRetail: Failed to fetch payment journals via RPC, using POS config methods:", err);
        }

        // Fallback to POS config payment methods (excluding pay later / credit)
        const pms = this.pos.payment_methods_from_config || [];
        const validPms = pms.filter(
            (p) => p.type !== "pay_later" && !/credit|khata|udhar/i.test(p.name || "")
        );
        this.state.journals = validPms.map((p) => ({
            id: p.id,
            name: p.name,
            type: p.is_cash_count ? "cash" : "bank",
            is_cash: Boolean(p.is_cash_count),
        }));
        if (this.state.journals.length) {
            this.state.journalId = this.state.journals[0].id;
        }
    }

    async refreshAllocation(amount) {
        const num = parseFloat(amount) || 0;
        if (num <= 0) {
            this.state.allocations = [];
            this.state.newTotal = this.state.previousTotal;
            this.state.newTotalFormatted = this.formatCurrency(this.state.previousTotal);
            this.state.unallocated = 0;
            this.state.unallocatedFormatted = this.formatCurrency(0);
            return;
        }

        this.state.loadingAllocations = true;
        this.state.errorMsg = "";
        try {
            const alloc = await this.pos.data.call(
                "res.partner",
                "get_customer_payment_allocation",
                [this.partner.id, num]
            );
            this.state.allocations = alloc.lines || [];
            this.state.previousTotal = alloc.previous_total_outstanding || 0;
            this.state.previousTotalFormatted = alloc.previous_total_outstanding_formatted;
            this.state.newTotal = alloc.new_total_outstanding || 0;
            this.state.newTotalFormatted = alloc.new_total_outstanding_formatted;
            this.state.unallocated = alloc.remaining_unallocated || 0;
            this.state.unallocatedFormatted = alloc.remaining_unallocated_formatted;
        } catch (err) {
            console.warn("PosRetail: Failed to compute live allocation:", err);
        } finally {
            this.state.loadingAllocations = false;
        }
    }

    onAmountInput(ev) {
        this.state.amount = ev.target.value;
        const num = parseFloat(this.state.amount) || 0;
        this.refreshAllocation(num);
    }

    setFullAmount() {
        const owed = this.partner.pos_outstanding_balance || 0;
        this.state.amount = String(Math.max(0, owed));
        this.refreshAllocation(owed);
    }

    setJournal(id) {
        this.state.journalId = id;
    }

    async onConfirm() {
        const amount = parseFloat(this.state.amount);
        if (!amount || amount <= 0) {
            this.state.errorMsg = _t("Please enter a valid payment amount greater than 0.");
            return;
        }

        this.state.submitting = true;
        this.state.errorMsg = "";
        try {
            const cashier = this.pos.getCashier();
            const result = await this.pos.data.call(
                "pos.retail.khata.payment",
                "pos_retail_settle_from_pos",
                [
                    this.partner.id,
                    amount,
                    cashier?.id || false,
                    this.state.journalId,
                    this.state.memo,
                    this.state.date,
                ]
            );

            // Update partner model in local POS memory
            this.partner.pos_outstanding_balance = result.new_balance;

            this.props.getPayload(result);
            this.props.close();
        } catch (error) {
            this.state.errorMsg =
                error?.data?.message ||
                error?.message ||
                _t("The payment could not be processed. Please check branch configuration.");
        } finally {
            this.state.submitting = false;
        }
    }
}
