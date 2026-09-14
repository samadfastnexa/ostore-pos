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
        const tmpl = line.product_id?.product_tmpl_id;
        const origPrice = line.price_unit || tmpl?.list_price || 0;
        const currentDiscount = line.discount || 0;
        const initialFixed = currentDiscount > 0 ? (origPrice * currentDiscount / 100) : 0;
        const initialFinalPrice = currentDiscount > 0 ? Math.max(0, origPrice - initialFixed) : origPrice;

        const defaultTab = this.props.initialMode === "price" ? "price" : "percent";

        this.state = useState({
            tab: defaultTab, // "percent" or "price"
            basePrice: origPrice, // Base unit price against which discounts are calculated
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

    get basePrice() {
        const val = parseFloat(this.state.basePrice);
        return Number.isFinite(val) && val > 0 ? val : (this.originalUnitPrice || 0);
    }

    setBasePrice(price) {
        const num = parseFloat(price);
        if (!Number.isFinite(num) || num <= 0) return;
        this.state.basePrice = num;
        if (this.state.tab === "percent") {
            const pct = this.currentPercent;
            const fp = Math.max(0, num * (1 - pct / 100));
            this.state.priceInput = fp.toFixed(2);
        } else {
            this.state.priceInput = num.toFixed(2);
            this.state.pctInput = "0";
        }
    }

    get defaultPrice() {
        return this.productTemplate?.list_price || this.originalUnitPrice;
    }

    get minPrice() {
        return this.line.pos_retail_min_price || this.productTemplate?.minimum_selling_price || this.product?.minimum_selling_price || 0;
    }

    get mrp() {
        return this.line.pos_retail_max_price || this.productTemplate?.mrp || this.product?.mrp || 0;
    }

    get maxPrice() {
        return this.mrp;
    }

    get hasPriceRange() {
        return Boolean(this.minPrice || this.maxPrice);
    }

    get isAboveMaximum() {
        if (!this.maxPrice) {
            return false;
        }
        return this.currentFinalPrice > this.maxPrice + 0.001;
    }

    get suggestedPrice() {
        const orig = this.basePrice || this.originalUnitPrice;
        if (orig <= 0) {
            return 0;
        }
        // 1. If product template has wholesale_price and it's valid:
        const wholesale = this.productTemplate?.wholesale_price || this.product?.wholesale_price || 0;
        if (wholesale > 0 && wholesale < orig && (!this.minPrice || wholesale >= this.minPrice)) {
            return wholesale;
        }
        // 2. Standard 10% discount if within allowed range:
        const tenPct = Math.round(orig * 0.90 * 100) / 100;
        if ((!this.minPrice || tenPct >= this.minPrice) && tenPct < orig) {
            return tenPct;
        }
        // 3. Midpoint between original and minPrice:
        if (this.minPrice > 0 && this.minPrice < orig) {
            return Math.round(((orig + this.minPrice) / 2) * 100) / 100;
        }
        // 4. Default 5% off:
        const fivePct = Math.round(orig * 0.95 * 100) / 100;
        if (!this.minPrice || fivePct >= this.minPrice) {
            return fivePct;
        }
        return this.minPrice || orig;
    }

    get suggestedDiscountPercent() {
        if (this.basePrice <= 0 || !this.suggestedPrice) {
            return 0;
        }
        const diff = Math.max(0, this.basePrice - this.suggestedPrice);
        return (diff / this.basePrice) * 100;
    }

    get suggestedPriceLabel() {
        const wholesale = this.productTemplate?.wholesale_price || this.product?.wholesale_price || 0;
        if (wholesale > 0 && this.suggestedPrice === wholesale) {
            return _t("Wholesale");
        }
        return _t("Suggested");
    }

    get isSuggestedPriceApplied() {
        return Math.abs(this.currentFinalPrice - this.suggestedPrice) < 0.01 && this.currentDiscountAmount > 0;
    }

    get currentPercent() {
        const val = parseFloat(this.state.pctInput);
        return Number.isFinite(val) && val >= 0 ? val : 0;
    }

    get currentFinalPrice() {
        if (this.state.tab === "price") {
            const val = parseFloat(this.state.priceInput);
            return Number.isFinite(val) && val >= 0 ? val : this.basePrice;
        }
        return Math.max(0, this.basePrice * (1 - this.currentPercent / 100));
    }

    get currentDiscountAmount() {
        return Math.max(0, this.basePrice - this.currentFinalPrice);
    }

    get totalDiscountAmount() {
        return this.currentDiscountAmount * (this.line.qty || 1);
    }

    get totalFinalPrice() {
        return this.currentFinalPrice * (this.line.qty || 1);
    }

    get maxAllowedDiscountPercent() {
        if (!this.minPrice || this.basePrice <= 0) {
            return 100;
        }
        const maxOff = Math.max(0, this.basePrice - this.minPrice);
        return Math.min(100, (maxOff / this.basePrice) * 100);
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
            // When switching to Discount % tab, compute discount against basePrice
            const priceNum = parseFloat(this.state.priceInput);
            if (Number.isFinite(priceNum) && priceNum > 0 && this.basePrice > 0) {
                if (priceNum > this.basePrice) {
                    this.state.basePrice = priceNum;
                    this.state.pctInput = "";
                } else {
                    const disc = Math.max(0, this.basePrice - priceNum);
                    const pct = (disc / this.basePrice) * 100;
                    this.state.pctInput = pct > 0.001 ? (Number.isInteger(pct) ? String(pct) : parseFloat(pct.toFixed(2)).toString()) : "";
                }
            }
        }
    }

    onPctInput(ev) {
        const val = ev.target.value;
        this.state.pctInput = val;
        const num = parseFloat(val);
        if (Number.isFinite(num) && num >= 0 && this.basePrice > 0) {
            const fp = Math.max(0, this.basePrice * (1 - num / 100));
            this.state.priceInput = fp.toFixed(2);
        } else {
            this.state.priceInput = this.basePrice.toFixed(2);
        }
    }

    onPriceInput(ev) {
        const val = ev.target.value;
        this.state.priceInput = val;
        const num = parseFloat(val);
        if (Number.isFinite(num) && num > 0) {
            if (num >= this.basePrice || (this.minPrice && this.basePrice === this.minPrice && num > this.minPrice)) {
                this.state.basePrice = num;
                this.state.pctInput = "";
            } else {
                const disc = Math.max(0, this.basePrice - num);
                const pct = (disc / this.basePrice) * 100;
                this.state.pctInput = pct > 0.001 ? (Number.isInteger(pct) ? String(pct) : parseFloat(pct.toFixed(2)).toString()) : "";
            }
        } else {
            this.state.pctInput = "";
        }
    }

    applyPresetPercent(pct) {
        this.state.tab = "percent";
        const num = parseFloat(pct);
        const validPct = Number.isFinite(num) ? num : 0;
        this.state.pctInput = validPct > 0 ? (Number.isInteger(validPct) ? String(validPct) : parseFloat(validPct.toFixed(2)).toString()) : "";
        if (this.basePrice > 0) {
            const fp = Math.max(0, this.basePrice * (1 - validPct / 100));
            this.state.priceInput = fp.toFixed(2);
        }
    }

    applyPresetPrice(price) {
        this.state.tab = "price";
        const num = parseFloat(price);
        if (Number.isFinite(num) && num > 0) {
            this.state.priceInput = num.toFixed(2);
            if (num >= this.basePrice || (this.minPrice && this.basePrice === this.minPrice && num > this.minPrice)) {
                this.state.basePrice = num;
                this.state.pctInput = "";
            } else {
                const disc = Math.max(0, this.basePrice - num);
                const pct = (disc / this.basePrice) * 100;
                this.state.pctInput = pct > 0.001 ? (Number.isInteger(pct) ? String(pct) : parseFloat(pct.toFixed(2)).toString()) : "";
            }
        }
    }

    applySuggestedPrice() {
        if (this.state.tab === "price") {
            this.applyPresetPrice(this.suggestedPrice);
        } else {
            this.applyPresetPercent(this.suggestedDiscountPercent);
        }
    }

    applyMaxAllowed() {
        this.applyPresetPercent(this.maxAllowedDiscountPercent);
    }

    clearAll() {
        this.state.pctInput = "";
        this.state.priceInput = this.basePrice.toFixed(2);
    }

    async confirm() {
        const pct = Math.min(100, Math.max(0, this.currentPercent));

        // Enforce Minimum Selling Price & Maximum MRP
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
        } else if (this.isAboveMaximum) {
            manager = await posRetailRequestManagerPin(this.pos, this.dialog, this.notification, {
                title: _t("Manager PIN — Above Maximum Price Approval"),
                noManagerMessage: _t("No manager is configured to approve selling above maximum price."),
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
        const basePrice = this.basePrice;

        // Apply to all products if checked
        if (this.state.applyToAll) {
            await this.applyDiscountToAll(basePrice, pct, inputType, this.state.reason, manager);
        } else {
            // Apply only to selected line
            this.applyDiscountToLine(this.line, basePrice, pct, inputType, this.state.reason, manager);
        }

        this.props.close();
    }

    applyDiscountToLine(line, basePrice, pct, mode, reason, manager) {
        if (basePrice && Math.abs((line.price_unit || 0) - basePrice) > 0.001) {
            line.setUnitPrice(basePrice);
            line.price_type = "manual";
        }
        line.setDiscount(pct);
        line.pos_retail_line_discount_input_type = mode;
        line.pos_retail_line_discount_reason = reason;
        line.pos_retail_line_discount_manager_id = manager || false;
        line.pos_retail_min_price = line.product_id?.product_tmpl_id?.minimum_selling_price || 0;
        line.pos_retail_default_price = line.product_id?.product_tmpl_id?.list_price || line.price_unit;
        line.pos_retail_max_price = line.product_id?.product_tmpl_id?.mrp || 0;
    }

    async applyDiscountToAll(basePrice, pct, mode, reason, manager) {
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
            const lineBase = line === this.line ? basePrice : (line.price_unit || 0);
            const min = line.pos_retail_min_price || line.product_id?.product_tmpl_id?.minimum_selling_price || 0;
            const finalPrice = lineBase * (1 - pct / 100);

            if (min && finalPrice < min - 0.001) {
                if (manager) {
                    this.applyDiscountToLine(line, lineBase, pct, mode, reason, manager);
                    appliedCount++;
                } else {
                    const maxAllowedPct = lineBase > 0 ? Math.max(0, ((lineBase - min) / lineBase) * 100) : 0;
                    blockedLines.push({
                        name: line.product_id?.display_name || _t("Product"),
                        minPrice: min,
                        maxAllowedPct: maxAllowedPct.toFixed(1),
                    });
                }
            } else {
                this.applyDiscountToLine(line, lineBase, pct, mode, reason, false);
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
