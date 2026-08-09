/** @odoo-module **/

import { _t } from "@web/core/l10n/translation";
import { Component, onWillStart, useState } from "@odoo/owl";
import { Dialog } from "@web/core/dialog/dialog";
import { usePos } from "@point_of_sale/app/hooks/pos_hook";

// Pick an existing quotation to update or duplicate.
//
// Quotations live on the server, not in the POS session, so this fetches on
// demand. Only draft and sent quotations are offered: a confirmed order is no
// longer a quotation, and rewriting one from a cart would rewrite a
// commitment the customer already accepted.
export class PosRetailQuotationPicker extends Component {
    static template = "pos_retail.QuotationPicker";
    static components = { Dialog };
    static props = {
        title: String,
        // Pre-filter to one customer when the cart already has one.
        partner: { type: [Object, { value: null }], optional: true },
        getPayload: Function,
        close: Function,
    };

    setup() {
        this.pos = usePos();
        this.state = useState({
            loading: true,
            failed: false,
            quotes: [],
            search: "",
            onlyThisCustomer: Boolean(this.props.partner),
        });
        onWillStart(() => this.load());
    }

    async load() {
        this.state.loading = true;
        this.state.failed = false;
        try {
            this.state.quotes = await this.pos.data.call(
                "sale.order",
                "_pos_retail_search_quotations",
                [],
                {
                    partner_id:
                        this.state.onlyThisCustomer && this.props.partner
                            ? this.props.partner.id
                            : false,
                }
            );
        } catch {
            this.state.failed = true;
        } finally {
            this.state.loading = false;
        }
    }

    async toggleCustomerFilter() {
        this.state.onlyThisCustomer = !this.state.onlyThisCustomer;
        await this.load();
    }

    get visibleQuotes() {
        const term = this.state.search.trim().toLowerCase();
        if (!term) {
            return this.state.quotes;
        }
        return this.state.quotes.filter(
            (q) =>
                q.name.toLowerCase().includes(term) ||
                (q.partner_name || "").toLowerCase().includes(term)
        );
    }

    money(value) {
        return this.pos.env.utils.formatCurrency(value || 0);
    }

    stateLabel(quote) {
        return quote.state === "draft" ? _t("Draft") : _t("Sent");
    }

    select(quote) {
        this.props.getPayload(quote);
        this.props.close();
    }
}
