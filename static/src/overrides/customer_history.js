/** @odoo-module **/

import { _t } from "@web/core/l10n/translation";
import { Component, onWillStart, useState } from "@odoo/owl";
import { Dialog } from "@web/core/dialog/dialog";
import { usePos } from "@point_of_sale/app/hooks/pos_hook";
import { useService } from "@web/core/utils/hooks";

// The customer's full history, fetched on demand.
//
// The POS session carries only recent orders and nothing about payments,
// invoices or the ledger, so this needs the server. That means it is the one
// part of the customer view that cannot work offline -- handled explicitly
// rather than failing with an empty screen.
export class PosRetailCustomerHistory extends Component {
    static template = "pos_retail.CustomerHistory";
    static components = { Dialog };
    static props = {
        partner: Object,
        close: Function,
    };

    setup() {
        this.pos = usePos();
        this.notification = useService("notification");
        this.state = useState({
            loading: true,
            failed: false,
            tab: "purchases",
            data: null,
        });

        onWillStart(async () => {
            try {
                const data = await this.pos.data.call(
                    "res.partner",
                    "get_pos_customer_history",
                    [[this.props.partner.id]]
                );
                this.state.data = data;
            } catch {
                this.state.failed = true;
            } finally {
                this.state.loading = false;
            }
        });
    }

    get tabs() {
        const d = this.state.data;
        return [
            { id: "purchases", label: _t("Buys Often"), count: d?.top_products?.length || 0 },
            { id: "sales", label: _t("Sales"), count: d?.sales_count || 0 },
            { id: "credit", label: _t("Credit Sales"), count: d?.credit_sales?.length || 0 },
            { id: "payments", label: _t("Payments"), count: d?.payments?.length || 0 },
            { id: "open", label: _t("Unpaid"), count: d?.open_invoices?.length || 0 },
            { id: "refunds", label: _t("Returns"), count: d?.refunds_count || 0 },
            { id: "quotations", label: _t("Quotations"), count: d?.quotations?.length || 0 },
        ];
    }

    setTab(id) {
        this.state.tab = id;
    }

    /** Put the customer's last basket back in the cart. */
    async repeatLastOrder() {
        const basket = this.state.data?.last_basket || [];
        if (!basket.length) {
            this.notification.add(_t("This customer has no previous order to repeat."), {
                type: "warning",
            });
            return;
        }
        let added = 0;
        const skipped = [];
        for (const item of basket) {
            const product = this.pos.models["product.product"].get(item.product_id);
            // A product can be gone from the catalogue, or no longer sold in
            // POS, since that order was rung up.
            if (!product) {
                skipped.push(item.name);
                continue;
            }
            await this.pos.addLineToCurrentOrder(
                { product_id: product, product_tmpl_id: product.product_tmpl_id, qty: item.qty },
                {}
            );
            added += 1;
        }
        // Prices come from today's catalogue, not the old order: charging a
        // stale price would be wrong, and silently so.
        if (added) {
            this.notification.add(
                _t("%s product(s) added at today's prices.", added),
                { type: "success" }
            );
        }
        if (skipped.length) {
            this.notification.add(
                _t("Not available any more: %s", skipped.join(", ")),
                { type: "warning" }
            );
        }
        this.props.close();
    }
}
