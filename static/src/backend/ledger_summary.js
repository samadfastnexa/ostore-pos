/** @odoo-module **/

import { Component, onWillStart, onWillUpdateProps, useState } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { formatMonetary } from "@web/views/fields/formatters";
import { listView } from "@web/views/list/list_view";
import { ListController } from "@web/views/list/list_controller";

// Summary cards above a ledger, recomputed for whatever is filtered.
//
// A ledger answers "how much" before it answers "which rows", so the totals
// sit above the table instead of in a footer the reader has to scroll to.
// They follow the search: filter to one customer, or to last month, and the
// cards describe exactly that.
//
// The figures come from the server rather than being added up here. The
// balance card is not a sum of rows -- it is each partner's balance as of
// their last transaction in range, added across partners -- and only the
// server has every row to work that out, not just the page on screen.
export class PosRetailLedgerSummary extends Component {
    static template = "pos_retail.LedgerSummary";
    static props = {
        resModel: String,
        domain: Array,
        cards: Array,
    };

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.state = useState({ loading: true, totals: {} });
        onWillStart(() => this.load(this.props.domain));
        onWillUpdateProps((next) => {
            // Only when the filters actually changed: a re-render for any other
            // reason (a row expanded, a column toggled) must not refetch.
            if (JSON.stringify(next.domain) !== JSON.stringify(this.props.domain)) {
                return this.load(next.domain);
            }
        });
    }

    async load(domain) {
        this.state.loading = true;
        try {
            this.state.totals = await this.orm.call(
                this.props.resModel, "pos_retail_ledger_summary", [domain]);
        } finally {
            this.state.loading = false;
        }
    }

    display(card) {
        const value = this.state.totals[card.key] ?? 0;
        if (card.kind === "count") {
            return String(value);
        }
        return formatMonetary(value, { currencyId: this.state.totals.currency_id });
    }

    get isCustomerLedger() {
        return this.props.resModel === "pos.retail.customer.ledger.line" ||
               this.props.resModel === "pos.retail.outstanding.customer";
    }

    get isVendorLedger() {
        return this.props.resModel === "pos.retail.vendor.ledger.line" ||
               this.props.resModel === "pos.retail.outstanding.vendor";
    }

    get partnerIdFromDomain() {
        if (!Array.isArray(this.props.domain)) {
            return false;
        }
        for (const leaf of this.props.domain) {
            if (Array.isArray(leaf) && leaf.length === 3 && leaf[0] === "partner_id" && (leaf[1] === "=" || leaf[1] === "in")) {
                const val = leaf[2];
                return Array.isArray(val) ? val[0] : val;
            }
        }
        return false;
    }

    onClickAdjustCustomerKhata() {
        const context = {};
        const pid = this.partnerIdFromDomain;
        if (pid) {
            context.default_partner_id = pid;
        }
        this.action.doAction({
            name: "Khata Adjustment",
            type: "ir.actions.act_window",
            res_model: "pos.retail.ledger.adjustment",
            views: [[false, "form"]],
            target: "new",
            context: context,
        });
    }

    onClickReceiveCustomerPayment() {
        const context = {};
        const pid = this.partnerIdFromDomain;
        if (pid) {
            context.default_partner_id = pid;
        }
        this.action.doAction({
            name: "Receive Khata Payment",
            type: "ir.actions.act_window",
            res_model: "pos.retail.khata.payment",
            views: [[false, "form"]],
            target: "new",
            context: context,
        });
    }

    // Add Customer / Add Vendor: the ledgers list entries, so a contact with
    // none is not on them -- this is the way onto the ledger from the ledger.
    onClickAddContact(side) {
        this.action.doAction({
            name: side === "vendor" ? "Add Vendor" : "Add Customer",
            type: "ir.actions.act_window",
            res_model: "pos.retail.ledger.contact.add",
            views: [[false, "form"]],
            target: "new",
            context: { default_side: side },
        });
    }

    onClickPayVendor() {
        const context = {};
        const pid = this.partnerIdFromDomain;
        if (pid) {
            context.default_partner_id = pid;
        }
        this.action.doAction({
            name: "Pay Vendor",
            type: "ir.actions.act_window",
            res_model: "pos.retail.vendor.payment",
            views: [[false, "form"]],
            target: "new",
            context: context,
        });
    }

    onClickAdjustVendorKhata() {
        const context = {};
        const pid = this.partnerIdFromDomain;
        if (pid) {
            context.default_partner_id = pid;
        }
        this.action.doAction({
            name: "Vendor Khata Adjustment",
            type: "ir.actions.act_window",
            res_model: "pos.retail.vendor.ledger.adjustment",
            views: [[false, "form"]],
            target: "new",
            context: context,
        });
    }
}

// Which cards each ledger shows. Kept separate on purpose: the vendor ledger
// counts purchases and payments MADE, the customer ledger sales and payments
// RECEIVED, and one shared set of labels would read wrong on one of them.
// `note` is a line of Roman Urdu shown under each figure, for the shop staff --
// above all what a minus balance means, which was being read as a debt.
const CARDS = {
    "pos.retail.customer.ledger.line": [
        { key: "sale_amount", label: "Total Sales", tone: "primary",
          note: "Customers ko itne ka maal becha. Purana khata is mein nahi aata." },
        { key: "payment_received", label: "Total Payments Received", tone: "success",
          note: "Customers se itne paisay mile." },
        { key: "refund_amount", label: "Total Refunds", tone: "warning",
          note: "Customers ne itne ka maal wapas kiya." },
        { key: "balance", label: "Total Outstanding", tone: "danger",
          hint: "What customers owed at their last transaction shown.",
          note: "Customers ne dukaan ko itna dena hai. Minus (-) ho to customer zyada de chuka hai." },
        { key: "count", label: "Number of Transactions", tone: "secondary", kind: "count",
          note: "Is list mein itni entries hain." },
    ],
    "pos.retail.vendor.ledger.line": [
        { key: "purchase_amount", label: "Total Purchases", tone: "primary",
          note: "Vendors se itne ka maal liya. Purana khata is mein nahi aata." },
        { key: "payment_made", label: "Total Payments Made", tone: "success",
          note: "Vendors ko itne paisay diye." },
        { key: "refund_amount", label: "Total Vendor Refunds", tone: "warning",
          note: "Vendors ko itne ka maal wapas kiya." },
        { key: "balance", label: "Total Payable", tone: "danger",
          hint: "What the shop owed suppliers at their last transaction shown.",
          note: "Dukaan ne vendors ko itna dena hai. Minus (-) ho to dukaan zyada de chuki hai." },
        { key: "count", label: "Number of Transactions", tone: "secondary", kind: "count",
          note: "Is list mein itni entries hain." },
    ],
    // One row per partner already, so there is no "as of last transaction"
    // subtlety here -- just a plain sum and count over whatever is filtered.
    "pos.retail.outstanding.customer": [
        { key: "total_outstanding", label: "Total Outstanding", tone: "danger",
          hint: "What every customer shown owes the shop right now.",
          note: "Customers ne dukaan ko itna dena hai. Minus (-) ho to customer zyada de chuka hai." },
        { key: "count", label: "Number of Customers", tone: "secondary", kind: "count",
          note: "Is list mein itne customers hain." },
    ],
    "pos.retail.outstanding.vendor": [
        { key: "total_outstanding", label: "Total Payable", tone: "danger",
          hint: "What the shop owes every supplier shown right now.",
          note: "Dukaan ne vendors ko itna dena hai. Minus (-) ho to dukaan zyada de chuki hai." },
        { key: "count", label: "Number of Vendors", tone: "secondary", kind: "count",
          note: "Is list mein itne vendors hain." },
    ],
};

export class PosRetailLedgerListController extends ListController {
    static template = "pos_retail.LedgerListView";
    static components = { ...ListController.components, PosRetailLedgerSummary };

    get posRetailCards() {
        return CARDS[this.props.resModel] || [];
    }
}

registry.category("views").add("pos_retail_ledger_list", {
    ...listView,
    Controller: PosRetailLedgerListController,
});
