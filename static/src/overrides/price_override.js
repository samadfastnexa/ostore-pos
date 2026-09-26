/** @odoo-module **/

import { patch } from "@web/core/utils/patch";
import { _t } from "@web/core/l10n/translation";
import { PosStore } from "@point_of_sale/app/services/pos_store";
import { PosOrderline } from "@point_of_sale/app/models/pos_order_line";
import { ProductScreen } from "@point_of_sale/app/screens/product_screen/product_screen";
import { OrderSummary } from "@point_of_sale/app/screens/product_screen/order_summary/order_summary";
import { SelectionPopup } from "@point_of_sale/app/components/popups/selection_popup/selection_popup";
import { makeAwaitable } from "@point_of_sale/app/utils/make_awaitable_dialog";
import { PriceSelectionPopup } from "./price_popup";
import { posRetailRequestManagerPin } from "../utils/manager_pin";
import { AlertDialog } from "@web/core/confirmation_dialog/confirmation_dialog";

// Flexible pricing: ask for the selling price as a ranged product is added.
//
// The hook is addLineToCurrentOrder rather than ProductScreen.addProductToOrder
// because the store method is the single funnel for card taps, barcode scans and
// GS1 scans alike, so scanning a ranged product is validated exactly like
// tapping it.
patch(PosStore.prototype, {
    /** A product is "ranged" only when a bound actually constrains the price. */
    posRetailHasPriceRange(productTemplate) {
        const minimum = productTemplate?.minimum_selling_price || 0;
        const maximum = productTemplate?.mrp || 0;
        return Boolean(minimum || maximum) && minimum !== maximum;
    },

    /**
     * Verify whether a product is sellable:
     * - Selling price must be greater than zero.
     * - In-hand stock must be positive for storable items, and cart quantity must not exceed available stock.
     */
    posRetailCheckSellable(vals, order = null) {
        const currentOrder = order || this.getOrder();
        // Allow returns / refunds (items returned to store)
        if (currentOrder?.preset_id?.is_return || currentOrder?.is_return || (vals.qty !== undefined && vals.qty < 0)) {
            return { ok: true };
        }

        let tmpl = vals.product_tmpl_id;
        if (typeof tmpl === "number") {
            tmpl = this.data.models["product.template"].get(tmpl);
        }
        let product = vals.product_id;
        if (typeof product === "number") {
            product = this.data.models["product.product"].get(product);
        }
        if (!product && tmpl?.product_variant_ids?.length === 1) {
            product = tmpl.product_variant_ids[0];
        }
        if (!tmpl && product?.product_tmpl_id) {
            tmpl = product.product_tmpl_id;
        }

        // Exempt system products (discount, tips, rounding)
        const discountProdId = this.config?.discount_product_id?.id;
        const tipProdId = this.config?.tip_product_id?.id;
        if (product && (product.id === discountProdId || product.id === tipProdId)) {
            return { ok: true };
        }

        const name = product?.display_name || tmpl?.name || _t("Product");
        const requestedQty = vals.qty !== undefined ? vals.qty : 1;

        // 1. Stock check: storable products must have available in-hand stock
        const isStorable = Boolean(tmpl?.is_storable ?? product?.is_storable);
        if (isStorable) {
            const variants = tmpl?.product_variant_ids || [];
            let inHand = 0;
            if (product && typeof product.qty_available === "number") {
                inHand = product.qty_available;
            } else if (variants.length > 0) {
                inHand = variants.reduce((sum, v) => sum + (v.qty_available || 0), 0);
            }

            if (inHand <= 0) {
                return {
                    ok: false,
                    title: _t("Out of Stock (0 in hand)"),
                    message: _t('"%s" is out of stock (0 in hand) and cannot be added to cart. Please update inventory before selling.', name),
                };
            }

            if (currentOrder && currentOrder.lines) {
                const currentCartQty = currentOrder.lines
                    .filter((line) => {
                        const lProd = line.getProduct ? line.getProduct() : line.product_id;
                        if (product && lProd) {
                            return lProd.id === product.id;
                        }
                        if (tmpl && (line.product_tmpl_id || lProd?.product_tmpl_id)) {
                            const lTmplId = line.product_tmpl_id?.id || lProd?.product_tmpl_id?.id;
                            return lTmplId === tmpl.id;
                        }
                        return false;
                    })
                    .reduce((sum, line) => {
                        const q = typeof line.getQuantity === "function" ? line.getQuantity() : (line.qty || 0);
                        return sum + q;
                    }, 0);

                if (currentCartQty + requestedQty > inHand) {
                    return {
                        ok: false,
                        title: _t("Insufficient Stock"),
                        message: _t('Cannot add "%s": Only %s available in hand (%s already in cart).', name, inHand, currentCartQty),
                    };
                }
            }
        }

        // 2. Price check: product must not have price 0
        const isCombo = Boolean(tmpl?.isCombo && tmpl.isCombo());
        if (!isCombo) {
            let price = vals.price_unit;
            if (price === undefined) {
                const pricelist = currentOrder?.pricelist_id || this.config?.pricelist_id || false;
                if (product && typeof product.getPrice === "function") {
                    price = product.getPrice(pricelist, requestedQty, 0, false, product);
                } else if (tmpl && typeof tmpl.getPrice === "function") {
                    price = tmpl.getPrice(pricelist, requestedQty, 0, false, product || tmpl.product_variant_ids?.[0]);
                } else {
                    price = tmpl?.list_price || product?.list_price || 0;
                }
            }

            if (!price || price <= 0) {
                return {
                    ok: false,
                    title: _t("Price is 0 (Unsellable)"),
                    message: _t('"%s" has a selling price of 0 and cannot be sold. Please set a selling price before adding to cart.', name),
                };
            }
        }

        return { ok: true };
    },

    async posRetailAskPriceReason() {
        const reasons = this.models["pos.retail.price.reason"].getAll();
        if (!reasons.length) {
            return null;
        }
        return makeAwaitable(this.dialog, SelectionPopup, {
            title: _t("Reason for the price override"),
            list: reasons.map((reason) => ({
                id: reason.id,
                label: reason.name,
                isSelected: false,
                item: reason,
            })),
        });
    },

    async addLineToCurrentOrder(vals, opts = {}, configure = true) {
        const order = this.getOrder() || this.addNewOrder();
        let tmpl = vals.product_tmpl_id;
        if (typeof tmpl === "number") {
            tmpl = this.data.models["product.template"].get(tmpl);
        }
        const isMultiVariant = Boolean(tmpl && tmpl.product_variant_ids && tmpl.product_variant_ids.length > 1 && !vals.product_id);

        if (!isMultiVariant) {
            const check = this.posRetailCheckSellable(vals, order);
            if (!check.ok) {
                this.sound?.play?.("error");
                this.dialog.add(AlertDialog, {
                    title: check.title,
                    body: check.message,
                });
                return false;
            }
        }

        const productTemplate = vals.product_tmpl_id;
        const shouldAsk =
            configure !== false &&
            this.config.pos_retail_price_range_enabled &&
            !("price_unit" in vals) &&
            this.posRetailHasPriceRange(productTemplate);

        if (!shouldAsk) {
            return await super.addLineToCurrentOrder(vals, opts, configure);
        }

        const payload = await makeAwaitable(this.dialog, PriceSelectionPopup, {
            product: productTemplate,
        });
        if (!payload) {
            // Cancelled: add nothing rather than silently falling back to the
            // default price, which the cashier may not have intended.
            return;
        }

        let manager = false;
        let reason = false;
        if (payload.isOutOfRange) {
            manager = await posRetailRequestManagerPin(this, this.dialog, this.notification, {
                noManagerMessage: _t("No manager is configured to approve price changes."),
            });
            if (!manager) {
                return;
            }
            if (this.config.pos_retail_price_override_requires_reason) {
                reason = await this.posRetailAskPriceReason();
                if (reason === false) {
                    return;
                }
            }
        }

        // Supplying price_unit is what makes core mark the line "manual", skip
        // the pricelist lookup and keep it out of any merge, so the chosen
        // price survives later pricelist/quantity changes.
        vals.price_unit = payload.price;
        const line = await super.addLineToCurrentOrder(vals, opts, configure);

        if (line) {
            line.pos_retail_default_price = productTemplate.list_price || 0;
            line.pos_retail_min_price = productTemplate.minimum_selling_price || 0;
            line.pos_retail_max_price = productTemplate.mrp || 0;
            line.pos_retail_price_state = payload.isOutOfRange
                ? "overridden"
                : payload.isDefault
                ? "default"
                : "adjusted";
            line.pos_retail_price_manager_id = manager || false;
            line.pos_retail_price_reason_id = reason || false;
        }
        return line;
    },

    async addLineToOrder(vals, order, opts = {}, configure = true) {
        const check = this.posRetailCheckSellable(vals, order);
        if (!check.ok) {
            this.sound?.play?.("error");
            this.dialog.add(AlertDialog, {
                title: check.title,
                body: check.message,
            });
            return false;
        }
        return await super.addLineToOrder(vals, order, opts, configure);
    },
});

// Colour the cart line by how its price was set. getDisplayClasses is core's
// purpose-built extension point for this (it returns {} in core) and its result
// is merged into the orderline's container classes.
patch(PosOrderline.prototype, {
    getDisplayClasses() {
        return {
            ...super.getDisplayClasses(),
            "pos-retail-line-adjusted": this.pos_retail_price_state === "adjusted",
            "pos-retail-line-overridden": this.pos_retail_price_state === "overridden",
        };
    },
});

// Editing the price of a line already in the cart (numpad "Price" mode) runs
// through the same range rules, so a price cannot be walked out of range after
// the fact to dodge the popup.
patch(OrderSummary.prototype, {
    async setLinePrice(line, price) {
        const newPrice = typeof price === "number" ? price : parseFloat(price);
        if (!Number.isFinite(newPrice) || newPrice <= 0) {
            this.dialog.add(AlertDialog, {
                title: _t("Invalid Price"),
                body: _t("Selling price must be greater than zero. Products with price 0 cannot be sold."),
            });
            return;
        }

        const product = line.product_id?.product_tmpl_id;
        const minimum = line.pos_retail_min_price || product?.minimum_selling_price || 0;
        const maximum = line.pos_retail_max_price || product?.mrp || 0;
        const outOfRange =
            Number.isFinite(newPrice) &&
            ((minimum && newPrice < minimum) || (maximum && newPrice > maximum));

        if (!this.pos.config.pos_retail_price_range_enabled || !outOfRange) {
            await super.setLinePrice(line, price);
            if (Number.isFinite(newPrice) && (minimum || maximum)) {
                const isDefault = newPrice === (product?.list_price || 0);
                line.pos_retail_price_state = isDefault ? "default" : "adjusted";
            }
            return;
        }

        // OrderSummary itself only injects number_buffer/dialog/pos, so the
        // notification service is reached through the store.
        const notification = this.pos.notification;
        notification.add(
            newPrice < minimum
                ? _t("The entered price is below the minimum selling price.")
                : _t("The entered price exceeds the maximum selling price."),
            { type: "warning" }
        );
        const manager = await posRetailRequestManagerPin(
            this.pos,
            this.dialog,
            notification,
            { noManagerMessage: _t("No manager is configured to approve price changes.") }
        );
        if (!manager) {
            return;
        }
        let reason = false;
        if (this.pos.config.pos_retail_price_override_requires_reason) {
            reason = await this.pos.posRetailAskPriceReason();
            if (reason === false) {
                return;
            }
        }

        await super.setLinePrice(line, price);
        line.pos_retail_min_price = minimum;
        line.pos_retail_max_price = maximum;
        line.pos_retail_default_price = product?.list_price || 0;
        line.pos_retail_price_state = "overridden";
        line.pos_retail_price_manager_id = manager;
        line.pos_retail_price_reason_id = reason || false;
    },
});

// Intercept direct taps on product cards in ProductScreen
patch(ProductScreen.prototype, {
    async addProductToOrder(product) {
        const order = this.pos.getOrder() || this.pos.addNewOrder();
        const check = this.pos.posRetailCheckSellable({ product_tmpl_id: product }, order);
        if (!check.ok) {
            this.pos.sound?.play?.("error");
            this.dialog.add(AlertDialog, {
                title: check.title,
                body: check.message,
            });
            return;
        }
        return await super.addProductToOrder(...arguments);
    },
});
