/** @odoo-module **/

import { Component, useState } from "@odoo/owl";
import { Dialog } from "@web/core/dialog/dialog";
import { _t } from "@web/core/l10n/translation";
import { usePos } from "@point_of_sale/app/hooks/pos_hook";
import { useService } from "@web/core/utils/hooks";

// Popup for a single "return without receipt" line: search/scan a product,
// choose the quantity and an adjustable refund price. Returns the choice; the
// caller creates the negative-qty line on an is_refund order.
//
// The shop's own case for this screen was specific: a cashier standing in
// front of a customer who has physically brought goods back has no time to
// go hunting through old orders first. Everything here is built around that
// -- product, quantity and a price are the only things that MUST be filled
// in, and the two things that would normally send someone to a search screen
// (who is this for, what was it originally sold on) are both here as
// optional extras rather than required steps.
export class ReturnNoReceiptPopup extends Component {
    static template = "pos_retail.ReturnNoReceiptPopup";
    static components = { Dialog };
    static props = { close: Function, getPayload: Function, order: { type: Object, optional: true } };

    setup() {
        this.pos = usePos();
        this.orm = useService("orm");
        this.state = useState({
            search: "", productId: false, qty: "1", price: "",
            // The optional link. Blank means "proceed unlinked", which is the
            // fast path and the default; nothing here forces a lookup.
            reference: "", linking: false, linkResult: null,
        });
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
        // A reference typed for a DIFFERENT product means nothing; changing
        // the product clears whatever the last lookup found.
        this.state.linkResult = null;
    }

    clearProduct() {
        this.state.productId = false;
        this.state.linkResult = null;
    }

    // The customer this return is for. Read from the ORDER, not held as
    // separate popup state: this.pos.selectPartner() (below) sets it directly
    // on the order, which is also where checkout and the accounting will read
    // it from, so there is exactly one place a customer can be recorded and
    // no way for the popup's idea of who it is to disagree with the order's.
    get partner() {
        return this.props.order?.getPartner();
    }

    async pickCustomer() {
        await this.pos.selectPartner(this.props.order);
    }

    // The optional link. Typed reference + the product already chosen is
    // enough to look for a matching original sale; nothing about entering
    // this popup or picking a product requires it.
    async lookupOriginal() {
        const reference = this.state.reference.trim();
        if (!reference || !this.selectedProduct) {
            return;
        }
        this.state.linking = true;
        try {
            const result = await this.orm.call(
                "pos.order", "pos_retail_find_return_source",
                [reference, this.selectedProduct.id]
            );
            this.state.linkResult = result;
            if (result.found) {
                // The point of linking at all: the ORIGINAL price, not
                // whatever the product happens to cost today.
                this.state.price = String(result.price_unit);
                // Never above what is actually left to return. Sold 25,
                // already returned 5 through some earlier visit -- typing 25
                // again here would return 5 of them a second time, silently,
                // months apart, which is exactly the mistake a receipt-free
                // return makes easy if nothing stops it.
                if (parseFloat(this.state.qty) > result.returnable_qty) {
                    this.state.qty = String(result.returnable_qty);
                }
            }
        } finally {
            this.state.linking = false;
        }
    }

    // The cap this popup enforces once a link is found. Read by the
    // template for the max= on the quantity field and by canConfirm, so the
    // two can never disagree about what is allowed.
    get maxQty() {
        return this.state.linkResult?.found ? this.state.linkResult.returnable_qty : Infinity;
    }

    clearLink() {
        this.state.reference = "";
        this.state.linkResult = null;
    }

    get canConfirm() {
        return Boolean(
            this.selectedProduct &&
                parseFloat(this.state.qty) > 0 &&
                parseFloat(this.state.qty) <= this.maxQty &&
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
            // Only a genuine match links the order. A reference that was
            // typed but not found, or found on an order without this
            // product, still leaves this return correctly marked unlinked --
            // half a lookup is not a link.
            originalOrderId: this.state.linkResult?.found ? this.state.linkResult.order_id : false,
            unlinked: !this.state.linkResult?.found,
        });
        this.props.close();
    }

    get linkStatusMessage() {
        const r = this.state.linkResult;
        if (!r || r.found) {
            return "";
        }
        if (r.reason === "no_matching_product") {
            return _t("Order %s does not have this product on it. Continuing without a link.", r.order_name);
        }
        return _t("No order found for that reference. Continuing without a link.");
    }
}
