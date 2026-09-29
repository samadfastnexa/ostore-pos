/** @odoo-module **/

import { Component, onWillStart, useState } from "@odoo/owl";
import { Dialog } from "@web/core/dialog/dialog";
import { _t } from "@web/core/l10n/translation";
import { usePos } from "@point_of_sale/app/hooks/pos_hook";
import { useService } from "@web/core/utils/hooks";

export class PosRetailQuotationModal extends Component {
    static template = "pos_retail.QuotationModal";
    static components = { Dialog };
    static props = {
        close: Function,
    };

    setup() {
        this.pos = usePos();
        this.notification = useService("notification");
        this.action = useService("action");

        const currentPartner = this.pos.getOrder()?.getPartner() || null;

        this.state = useState({
            loading: true,
            searchQuery: "",
            filter: "all",
            onlyThisCustomer: false,
            currentPartner: currentPartner,
            quotations: [],
            isLoadingLines: false,
            errorMessage: "",
        });

        onWillStart(async () => {
            await this.fetchQuotations();
        });
    }

    async fetchQuotations() {
        this.state.loading = true;
        this.state.errorMessage = "";
        try {
            const partnerId =
                this.state.onlyThisCustomer && this.state.currentPartner
                    ? this.state.currentPartner.id
                    : false;
            const res = await this.pos.data.call(
                "sale.order",
                "_pos_retail_search_quotations",
                [],
                { partner_id: partnerId, limit: 50 }
            );
            this.state.quotations = res || [];
        } catch (err) {
            this.state.errorMessage =
                err?.data?.message || err?.message || _t("Failed to load quotations.");
        } finally {
            this.state.loading = false;
        }
    }

    onSearchInput(ev) {
        this.state.searchQuery = ev.target.value;
    }

    clearSearch() {
        this.state.searchQuery = "";
    }

    toggleCustomerFilter() {
        this.state.onlyThisCustomer = !this.state.onlyThisCustomer;
        this.fetchQuotations();
    }

    setFilter(filterName) {
        this.state.filter = filterName;
    }

    get filteredQuotations() {
        let list = this.state.quotations;

        if (this.state.filter !== "all") {
            list = list.filter((q) => q.state === this.state.filter);
        }

        const term = (this.state.searchQuery || "").trim().toLowerCase();
        if (term) {
            list = list.filter(
                (q) =>
                    (q.name || "").toLowerCase().includes(term) ||
                    (q.partner_name || "").toLowerCase().includes(term)
            );
        }

        return list;
    }

    formatMoney(val) {
        return this.pos.env.utils.formatCurrency(val || 0);
    }

    async loadQuoteIntoCart(quote) {
        this.state.isLoadingLines = true;
        try {
            const res = await this.pos.data.call(
                "sale.order",
                "_pos_retail_get_quotation_lines",
                [quote.id]
            );

            if (!res || !res.lines || !res.lines.length) {
                this.notification.add(_t("This quotation has no items."), { type: "warning" });
                return;
            }

            const currentOrder = this.pos.getOrder();

            if (res.partner_id) {
                const partner = this.pos.models["res.partner"].get(res.partner_id);
                if (partner) {
                    currentOrder.setPartner(partner);
                }
            }

            let addedCount = 0;
            for (const item of res.lines) {
                const prod = this.pos.models["product.product"].get(item.product_id);
                if (prod) {
                    await this.pos.addLineToCurrentOrder(
                        {
                            product_id: prod,
                            product_tmpl_id: prod.product_tmpl_id,
                            qty: item.qty,
                            price_unit: item.price_unit,
                            discount: item.discount || 0,
                        },
                        {}
                    );
                    addedCount += 1;
                }
            }

            this.notification.add(
                _t("Loaded %(count)s item(s) from %(quote)s into the order.", {
                    count: addedCount,
                    quote: quote.name,
                }),
                { type: "success" }
            );

            this.props.close();
        } catch (err) {
            this.state.errorMessage =
                err?.data?.message || err?.message || _t("Could not load quotation lines.");
        } finally {
            this.state.isLoadingLines = false;
        }
    }

    async printQuotationPdf(quote) {
        try {
            await this.action.doAction({
                type: "ir.actions.report",
                report_name: "sale.report_saleorder",
                report_type: "qweb-pdf",
                context: { active_ids: [quote.id] },
            });
        } catch (err) {
            this.notification.add(_t("Could not print quotation PDF."), { type: "danger" });
        }
    }

    async duplicateQuotation(quote) {
        try {
            const copy = await this.pos.data.call(
                "sale.order",
                "_pos_retail_duplicate_quotation",
                [quote.id]
            );
            this.notification.add(
                _t("Duplicated %(old)s to fresh draft %(new)s.", {
                    old: quote.name,
                    new: copy.name,
                }),
                { type: "success" }
            );
            await this.fetchQuotations();
        } catch (err) {
            this.notification.add(_t("Could not duplicate quotation."), { type: "danger" });
        }
    }
}
