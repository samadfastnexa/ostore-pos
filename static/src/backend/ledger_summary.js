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
}

// Which cards each ledger shows. Kept separate on purpose: the vendor ledger
// counts purchases and payments MADE, the customer ledger sales and payments
// RECEIVED, and one shared set of labels would read wrong on one of them.
const CARDS = {
    "pos.retail.customer.ledger.line": [
        { key: "sale_amount", label: "Total Sales", tone: "primary" },
        { key: "payment_received", label: "Total Payments Received", tone: "success" },
        { key: "refund_amount", label: "Total Refunds", tone: "warning" },
        { key: "balance", label: "Total Outstanding", tone: "danger",
          hint: "What customers owed at their last transaction shown." },
        { key: "count", label: "Number of Transactions", tone: "secondary", kind: "count" },
    ],
    "pos.retail.vendor.ledger.line": [
        { key: "purchase_amount", label: "Total Purchases", tone: "primary" },
        { key: "payment_made", label: "Total Payments Made", tone: "success" },
        { key: "refund_amount", label: "Total Vendor Refunds", tone: "warning" },
        { key: "balance", label: "Total Payable", tone: "danger",
          hint: "What the shop owed suppliers at their last transaction shown." },
        { key: "count", label: "Number of Transactions", tone: "secondary", kind: "count" },
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
