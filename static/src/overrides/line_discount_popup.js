/** @odoo-module **/

import { Component, useState } from "@odoo/owl";
import { Dialog } from "@web/core/dialog/dialog";
import { _t } from "@web/core/l10n/translation";
import { usePos } from "@point_of_sale/app/hooks/pos_hook";
import { useService } from "@web/core/utils/hooks";
import { AlertDialog } from "@web/core/confirmation_dialog/confirmation_dialog";
import { posRetailRequestManagerPin } from "../utils/manager_pin";

export class LineDiscountPopup extends Component {
    static template = "pos_retail.LineDiscountPopup";
    static components = { Dialog };
    static props = {
        close: Function,
        getPayload: Function,
        line: Object,
        initialMode: { type: String, optional: true },
    };

    setup() {
        this.pos = usePos();
        this.dialog = useService("dialog");
        this.notification = useService("notification");

        const line = this.props.line;
        const origPrice = line.price_unit || 0;
        const currentDiscount = line.discount || 0;
        const initialFixed = currentDiscount > 0 ? (origPrice * currentDiscount / 100) : 0;
        const initialFinalPrice = currentDiscount > 0 ? Math.max(0, origPrice - initialFixed) : origPrice;

        const defaultTab = this.props.initialMode === "price" ? "price" : "percent";

        this.state = useState({
            tab: defaultTab, // "percent" or "price"
            pctInput: currentDiscount > 0 ? String(currentDiscount) : "",
            priceInput: currentDiscount > 0 ? initialFinalPrice.toFixed(2) : origPrice.toFixed(2),
            reason: line.pos_retail_line_discount_reason || "",
            applyToAll: false,
        });
    }

    get line() {
        return this.props.line;
    }

    get product() {
        return this.line.product_id;
    }

    get productTemplate() {
        return this.line.product_id?.product_tmpl_id;
    }

    get originalUnitPrice() {
        return this.line.price_unit || 0;
    }

    get defaultPrice() {
        return this.productTemplate?.list_price || this.originalUnitPrice;
    }

    get minPrice() {
        return this.line.pos_retail_min_price || this.productTemplate?.minimum_selling_price || 0;
    }

    get mrp() {
        return this.line.pos_retail_max_price || this.productTemplate?.mrp || 0;
    }

    get currentPercent() {
        const val = parseFloat(this.state.pctInput);
        return Number.isFinite(val) && val >= 0 ? val : 0;
    }

    get currentFinalPrice() {
        if (this.state.tab === "price") {
            const val = parseFloat(this.state.priceInput);
            return Number.isFinite(val) && val >= 0 ? val : this.originalUnitPrice;
        }
        return Math.max(0, this.originalUnitPrice * (1 - this.currentPercent / 100));
    }

    get currentDiscountAmount() {
        return Math.max(0, this.originalUnitPrice - this.currentFinalPrice);
    }

    get totalDiscountAmount() {
        return this.currentDiscountAmount * (this.line.qty || 1);
    }

    get totalFinalPrice() {
        return this.currentFinalPrice * (this.line.qty || 1);
    }

    get maxAllowedDiscountPercent() {
        if (!this.minPrice || this.originalUnitPrice <= 0) {
            return 100;
        }
        const maxOff = Math.max(0, this.originalUnitPrice - this.minPrice);
        return Math.min(100, (maxOff / this.originalUnitPrice) * 100);
    }

    get isBelowMinimum() {
        if (!this.minPrice) {
            return false;
        }
        return this.currentFinalPrice < this.minPrice - 0.001;
    }

    get canManagerOverride() {
        return Boolean(this.pos.config.pos_retail_line_discount_manager_below_min);
    }

    formatCurrency(amount) {
        if (this.env?.utils?.formatCurrency) {
            return this.env.utils.formatCurrency(amount || 0);
        }
        return (amount || 0).toFixed(2);
    }

    setTab(newTab) {
        this.state.tab = newTab;
        if (newTab === "price") {
            this.state.priceInput = this.currentFinalPrice.toFixed(2);
        } else {
            this.state.pctInput = this.currentPercent > 0 ? this.currentPercent.toFixed(2) : "";
        }
    }

    onPctInput(ev) {
        const val = ev.target.value;
        this.state.pctInput = val;
        const num = parseFloat(val);
        if (Number.isFinite(num) && num >= 0 && this.originalUnitPrice > 0) {
            const fp = Math.max(0, this.originalUnitPrice * (1 - num / 100));
            this.state.priceInput = fp.toFixed(2);
        } else {
            this.state.priceInput = this.originalUnitPrice.toFixed(2);
        }
    }

    onPriceInput(ev) {
        const val = ev.target.value;
        this.state.priceInput = val;
        const num = parseFloat(val);
        if (Number.isFinite(num) && num >= 0 && this.originalUnitPrice > 0) {
            const disc = Math.max(0, this.originalUnitPrice - num);
            const pct = (disc / this.originalUnitPrice) * 100;
            this.state.pctInput = pct.toFixed(2);
        } else {
            this.state.pctInput = "";
        }
    }

    applyPresetPercent(pct) {
        this.state.tab = "percent";
        this.state.pctInput = String(pct);
        if (this.originalUnitPrice > 0) {
            const fp = Math.max(0, this.originalUnitPrice * (1 - pct / 100));
            this.state.priceInput = fp.toFixed(2);
        }
    }

    applyPresetPrice(price) {
        this.state.tab = "price";
        const num = parseFloat(price);
        if (Number.isFinite(num) && this.originalUnitPrice > 0) {
            this.state.priceInput = num.toFixed(2);
            const disc = Math.max(0, this.originalUnitPrice - num);
            const pct = (disc / this.originalUnitPrice) * 100;
            this.state.pctInput = pct.toFixed(2);
        }
    }

    applyMaxAllowed() {
        if (this.minPrice > 0) {
            this.applyPresetPrice(this.minPrice);
        } else {
            this.applyPresetPercent(100);
        }
    }

    clearAll() {
        this.state.pctInput = "0";
        this.state.priceInput = this.originalUnitPrice.toFixed(2);
    }

    async confirm() {
        const pct = Math.min(100, Math.max(0, this.currentPercent));

        // Enforce Minimum Selling Price
        let manager = false;
        if (this.isBelowMinimum) {
            if (!this.canManagerOverride) {
                this.dialog.add(AlertDialog, {
                    title: _t("⚠️ Discount Not Allowed"),
                    body: _t(
                        "The entered price is below the minimum allowed price.\n\n" +
                        "Minimum Selling Price: %s\n" +
                        "Entered Price: %s\n\n" +
                        "Please adjust the discount or price.",
                        this.formatCurrency(this.minPrice),
                        this.formatCurrency(this.currentFinalPrice)
                    ),
                });
                return;
            }

            // Manager Override flow
            manager = await posRetailRequestManagerPin(this.pos, this.dialog, this.notification, {
                title: _t("Manager PIN — Below Minimum Price Approval"),
                noManagerMessage: _t("No manager is configured to approve selling below minimum price."),
            });
            if (!manager) {
                return;
            }
        }

        // Check if discount reason is required
        if (this.pos.config.pos_retail_line_discount_require_reason && pct > 0 && !this.state.reason.trim()) {
            this.notification.add(_t("Please enter a reason for the discount."), { type: "warning" });
            return;
        }

        const inputType = this.state.tab === "price" ? "fixed" : "percent";

        // Apply to all products if checked
        if (this.state.applyToAll) {
            await this.applyDiscountToAll(pct, inputType, this.state.reason, manager);
        } else {
            // Apply only to selected line
            this.applyDiscountToLine(this.line, pct, inputType, this.state.reason, manager);
        }

        this.props.close();
    }

    applyDiscountToLine(line, pct, mode, reason, manager) {
        line.setDiscount(pct);
        line.pos_retail_line_discount_input_type = mode;
        line.pos_retail_line_discount_reason = reason;
        line.pos_retail_line_discount_manager_id = manager || false;
        line.pos_retail_min_price = line.product_id?.product_tmpl_id?.minimum_selling_price || 0;
        line.pos_retail_default_price = line.product_id?.product_tmpl_id?.list_price || line.price_unit;
        line.pos_retail_max_price = line.product_id?.product_tmpl_id?.mrp || 0;
    }

    async applyDiscountToAll(pct, mode, reason, manager) {
        const order = this.pos.getOrder();
        if (!order) {
            return;
        }

        const lines = order.lines || [];
        let appliedCount = 0;
        const blockedLines = [];

        for (const line of lines) {
            if (line.qty <= 0 || line.refunded_orderline_id || line.isGlobalDiscountLine?.()) {
                continue;
            }
            const orig = line.price_unit || 0;
            const min = line.pos_retail_min_price || line.product_id?.product_tmpl_id?.minimum_selling_price || 0;
            const finalPrice = orig * (1 - pct / 100);

            if (min && finalPrice < min - 0.001) {
                if (manager) {
                    this.applyDiscountToLine(line, pct, mode, reason, manager);
                    appliedCount++;
                } else {
                    const maxAllowedPct = orig > 0 ? Math.max(0, ((orig - min) / orig) * 100) : 0;
                    blockedLines.push({
                        name: line.product_id?.display_name || _t("Product"),
                        minPrice: min,
                        maxAllowedPct: maxAllowedPct.toFixed(1),
                    });
                }
            } else {
                this.applyDiscountToLine(line, pct, mode, reason, false);
                appliedCount++;
            }
        }

        if (blockedLines.length > 0) {
            const listStr = blockedLines
                .map((b) => `• ${b.name}: Min ${this.formatCurrency(b.minPrice)} (Max Allowed: ${b.maxAllowedPct}%)`)
                .join("\n");

            this.dialog.add(AlertDialog, {
                title: _t("Discount Applied With Exceptions"),
                body: _t(
                    "Applied %s%% discount to %s product(s).\n\n" +
                    "The discount could not be applied to %s product(s) because it would fall below their minimum selling price:\n\n%s",
                    pct,
                    appliedCount,
                    blockedLines.length,
                    listStr
                ),
            });
        } else {
            this.notification.add(
                _t("Applied %s%% discount to all products (%s lines).", pct, appliedCount),
                { type: "success" }
            );
        }
    }
}
