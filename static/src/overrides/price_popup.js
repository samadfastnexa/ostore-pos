/** @odoo-module **/

import { Component, useState } from "@odoo/owl";
import { Dialog } from "@web/core/dialog/dialog";
import { _t } from "@web/core/l10n/translation";
import { usePos } from "@point_of_sale/app/hooks/pos_hook";

// Quick price selection, shown as a ranged product is added to the cart.
// Offers the minimum, the default and the maximum as one-tap choices plus a
// free entry, and validates live. It never performs the manager approval
// itself: it reports isOutOfRange and the caller (price_override.js) owns the
// PIN challenge, so the approval flow lives in one place.
export class PriceSelectionPopup extends Component {
    static template = "pos_retail.PriceSelectionPopup";
    static components = { Dialog };
    static props = { close: Function, getPayload: Function, product: Object };

    setup() {
        this.pos = usePos();
        this.state = useState({ price: String(this.defaultPrice) });
    }

    get product() {
        return this.props.product;
    }
    get defaultPrice() {
        return this.props.product.list_price || 0;
    }
    get minPrice() {
        return this.props.product.minimum_selling_price || 0;
    }
    get maxPrice() {
        return this.props.product.mrp || 0;
    }

    get enteredPrice() {
        const value = parseFloat(this.state.price);
        return Number.isFinite(value) ? value : null;
    }

    /** invalid | below | above | default | adjusted */
    get status() {
        const price = this.enteredPrice;
        if (price === null || price < 0) {
            return "invalid";
        }
        if (this.minPrice && price < this.minPrice) {
            return "below";
        }
        if (this.maxPrice && price > this.maxPrice) {
            return "above";
        }
        return price === this.defaultPrice ? "default" : "adjusted";
    }

    get isOutOfRange() {
        return this.status === "below" || this.status === "above";
    }

    get canConfirm() {
        return this.status !== "invalid";
    }

    // Colour language: green = default, orange = adjusted in range,
    // red = outside the range (manager approval needed).
    get statusClass() {
        return {
            default: "pos-retail-price-ok",
            adjusted: "pos-retail-price-adjusted",
            below: "pos-retail-price-blocked",
            above: "pos-retail-price-blocked",
            invalid: "pos-retail-price-blocked",
        }[this.status];
    }

    get message() {
        switch (this.status) {
            case "below":
                return _t("The entered price is below the minimum selling price.");
            case "above":
                return _t("The entered price exceeds the maximum selling price.");
            case "invalid":
                return _t("Enter a valid price.");
            case "adjusted":
                return _t("Within the allowed range.");
            default:
                return _t("Standard price.");
        }
    }

    get confirmLabel() {
        return this.isOutOfRange ? _t("Approve and Add") : _t("Add to Cart");
    }

    get formattedRange() {
        const format = this.env.utils.formatCurrency;
        if (this.minPrice && this.maxPrice) {
            return `${format(this.minPrice)} - ${format(this.maxPrice)}`;
        }
        return this.minPrice
            ? _t("from %s", format(this.minPrice))
            : _t("up to %s", format(this.maxPrice));
    }

    formatPrice(value) {
        return this.env.utils.formatCurrency(value);
    }

    setPrice(value) {
        this.state.price = String(value);
    }

    confirm() {
        if (!this.canConfirm) {
            return;
        }
        this.props.getPayload({
            price: this.enteredPrice,
            isOutOfRange: this.isOutOfRange,
            isDefault: this.status === "default",
        });
        this.props.close();
    }
}
