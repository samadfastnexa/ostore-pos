/** @odoo-module **/

import { Component, onWillStart, useState } from "@odoo/owl";
import { Dialog } from "@web/core/dialog/dialog";
import { _t } from "@web/core/l10n/translation";
import { usePos } from "@point_of_sale/app/hooks/pos_hook";
import { useService } from "@web/core/utils/hooks";

export class PosRetailStockModal extends Component {
    static template = "pos_retail.StockModal";
    static components = { Dialog };
    static props = {
        close: Function,
    };

    setup() {
        this.pos = usePos();
        this.notification = useService("notification");

        this.state = useState({
            loading: true,
            searchQuery: "",
            filter: "all",
            locationName: "",
            products: [],
            adjustingProduct: null,
            adjustCount: "",
            adjustNote: "",
            isSavingAdjust: false,
            errorMessage: "",
        });

        this._searchTimeout = null;

        onWillStart(async () => {
            await this.fetchStock("");
        });
    }

    async fetchStock(query = "") {
        this.state.loading = true;
        this.state.errorMessage = "";
        try {
            const res = await this.pos.data.call(
                "pos.session",
                "pos_retail_search_stock",
                [this.pos.config.id, query, 100]
            );
            this.state.locationName = res.location_name || "";
            this.state.products = res.products || [];
        } catch (err) {
            this.state.errorMessage =
                err?.data?.message || err?.message || _t("Failed to load inventory.");
        } finally {
            this.state.loading = false;
        }
    }

    onSearchInput(ev) {
        const query = ev.target.value;
        this.state.searchQuery = query;
        if (this._searchTimeout) {
            clearTimeout(this._searchTimeout);
        }
        this._searchTimeout = setTimeout(async () => {
            await this.fetchStock(this.state.searchQuery);
        }, 300);
    }

    clearSearch() {
        this.state.searchQuery = "";
        this.fetchStock("");
    }

    setFilter(filterName) {
        this.state.filter = filterName;
    }

    get filteredProducts() {
        const list = this.state.products;
        if (this.state.filter === "in_stock") {
            return list.filter((p) => p.on_hand > 5);
        } else if (this.state.filter === "low_stock") {
            return list.filter((p) => p.on_hand > 0 && p.on_hand <= 5);
        } else if (this.state.filter === "out_of_stock") {
            return list.filter((p) => p.on_hand <= 0);
        }
        return list;
    }

    formatMoney(val) {
        return this.pos.env.utils.formatCurrency(val || 0);
    }

    openAdjust(product) {
        this.state.adjustingProduct = product;
        this.state.adjustCount = String(product.on_hand);
        this.state.adjustNote = "";
        this.state.errorMessage = "";
    }

    closeAdjust() {
        this.state.adjustingProduct = null;
        this.state.adjustCount = "";
        this.state.adjustNote = "";
    }

    async submitAdjust() {
        const product = this.state.adjustingProduct;
        if (!product) return;

        const countVal = parseFloat(this.state.adjustCount);
        if (isNaN(countVal) || countVal < 0) {
            this.state.errorMessage = _t("Please enter a valid positive number for stock count.");
            return;
        }

        this.state.isSavingAdjust = true;
        this.state.errorMessage = "";

        try {
            const cashierId = this.pos.getCashier()?.id || false;
            const res = await this.pos.data.call(
                "pos.session",
                "pos_retail_adjust_stock",
                [
                    this.pos.config.id,
                    product.id,
                    countVal,
                    cashierId,
                    this.state.adjustNote || false,
                ]
            );

            product.on_hand = res.on_hand;
            await this.pos.data.read("product.product", [product.id]);

            this.notification.add(
                _t("%(name)s stock adjusted to %(qty)s %(uom)s.", {
                    name: product.name,
                    qty: res.on_hand,
                    uom: product.uom,
                }),
                { type: "success" }
            );

            this.closeAdjust();
        } catch (err) {
            this.state.errorMessage =
                err?.data?.message || err?.message || _t("Could not adjust stock.");
        } finally {
            this.state.isSavingAdjust = false;
        }
    }

    async addToCart(product) {
        const prod = this.pos.models["product.product"].get(product.id);
        if (!prod) {
            this.notification.add(_t("Product not loaded in active catalog."), { type: "warning" });
            return;
        }

        await this.pos.addLineToCurrentOrder(
            { product_id: prod, product_tmpl_id: prod.product_tmpl_id, qty: 1 },
            {}
        );

        this.notification.add(_t("Added 1x %(name)s to order.", { name: product.name }), {
            type: "success",
        });
    }
}
