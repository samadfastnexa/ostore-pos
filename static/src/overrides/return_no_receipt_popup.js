/** @odoo-module **/

import { Component, useState } from "@odoo/owl";
import { Dialog } from "@web/core/dialog/dialog";
import { usePos } from "@point_of_sale/app/hooks/pos_hook";

// Popup for a single "return without receipt" line: search/scan a product,
// choose the quantity and an adjustable refund price. Returns the choice; the
// caller creates the negative-qty line on an is_refund order.
export class ReturnNoReceiptPopup extends Component {
    static template = "pos_retail.ReturnNoReceiptPopup";
    static components = { Dialog };
    static props = { close: Function, getPayload: Function };

    setup() {
        this.pos = usePos();
        this.state = useState({ search: "", productId: false, qty: "1", price: "" });
    }

    get products() {
        const all = this.pos.models["product.product"]
            .getAll()
            .filter((p) => p.available_in_pos);
        const word = this.state.search.trim();
        const list = word ? this.pos.getProductsBySearchWord(word, all) : all;
        return list.slice(0, 20);
    }

    get selectedProduct() {
        return this.state.productId
            ? this.pos.models["product.product"].get(this.state.productId)
            : false;
    }

    selectProduct(product) {
        this.state.productId = product.id;
        this.state.price = String(product.lst_price || 0);
    }

    clearProduct() {
        this.state.productId = false;
    }

    get canConfirm() {
        return Boolean(
            this.selectedProduct &&
                parseFloat(this.state.qty) > 0 &&
                parseFloat(this.state.price) >= 0
        );
    }

    confirm() {
        if (!this.canConfirm) {
            return;
        }
        this.props.getPayload({
            product: this.selectedProduct,
            qty: parseFloat(this.state.qty),
            price: parseFloat(this.state.price),
        });
        this.props.close();
    }
}
