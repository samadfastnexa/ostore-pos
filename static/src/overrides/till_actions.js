/** @odoo-module **/

import { patch } from "@web/core/utils/patch";
import { _t } from "@web/core/l10n/translation";
import { ControlButtons } from "@point_of_sale/app/screens/product_screen/control_buttons/control_buttons";
import { makeAwaitable } from "@point_of_sale/app/utils/make_awaitable_dialog";
import { NumberPopup } from "@point_of_sale/app/components/popups/number_popup/number_popup";
import { AlertDialog } from "@web/core/confirmation_dialog/confirmation_dialog";

// Two more jobs a cashier does at a busy counter, put where they do them.
//
// Both read the capability the shop wired to a permission, so the Roles &
// Permissions screen decides who sees them. Hiding a button is a courtesy:
// the server re-checks the same permission against the EMPLOYEE, because a
// till is one shared login and anything decided in the browser is decided
// identically for everyone who ever stands at it.
patch(ControlButtons.prototype, {
    get posRetailCanAdjustStock() {
        return Boolean(this.pos.getCashier()?._can_stock_adjust);
    },

    get posRetailCanSeeDailySales() {
        return Boolean(this.pos.getCashier()?._can_daily_sales);
    },

    // The product to correct: whatever line is selected in the cart. Chosen
    // over a product picker because the case this exists for is a sale that
    // has just stopped -- the item is already in the cart and already the
    // thing being argued about.
    get posRetailStockTarget() {
        return this.pos.getOrder()?.getSelectedOrderline()?.product_id;
    },

    async onClickAdjustStock() {
        const product = this.posRetailStockTarget;
        if (!product) {
            this.dialog.add(AlertDialog, {
                title: _t("Which product?"),
                body: _t(
                    "Add the product to the order and select its line first, then " +
                        "correct the stock. Correcting the wrong product's count is " +
                        "harder to notice than it is to avoid."
                ),
            });
            return;
        }

        try {
            const before = await this.pos.data.call("pos.session", "pos_retail_stock_snapshot", [
                this.pos.config.id,
                product.id,
            ]);
            const counted = await makeAwaitable(this.dialog, NumberPopup, {
                title: _t("Count of %s", before.product_name),
                subtitle: _t("System says %(qty)s %(uom)s at %(where)s", {
                    qty: before.on_hand,
                    uom: before.uom,
                    where: before.location_name,
                }),
                startingValue: before.on_hand,
            });
            if (counted === null || counted === undefined || counted === "") {
                return;
            }

            const after = await this.pos.data.call("pos.session", "pos_retail_adjust_stock", [
                this.pos.config.id,
                product.id,
                parseFloat(counted),
                this.pos.getCashier().id,
            ]);
            // Refreshed from the server rather than assumed: the correction is
            // a real inventory adjustment, and other tills may have sold the
            // same item in the meantime.
            await this.pos.data.read("product.product", [product.id]);
            this.notification.add(
                _t("%(name)s is now %(qty)s %(uom)s.", {
                    name: after.product_name,
                    qty: after.on_hand,
                    uom: after.uom,
                }),
                { type: "success" }
            );
        } catch (error) {
            this.dialog.add(AlertDialog, {
                title: _t("Stock not corrected"),
                body:
                    error?.data?.message ||
                    error?.message ||
                    _t("The count could not be saved. Nothing was changed."),
            });
        }
    },

    async onClickDailySales() {
        try {
            const data = await this.pos.data.call("pos.session", "pos_retail_daily_sales", [
                this.pos.config.id,
                this.pos.getCashier().id,
            ]);
            const money = (value) => this.env.utils.formatCurrency(value);
            const lines = [
                _t("Register: %s", data.register),
                "",
                _t("Sales: %(count)s order(s), %(total)s", {
                    count: data.order_count,
                    total: money(data.sales_total),
                }),
            ];
            if (data.refund_count) {
                lines.push(
                    _t("Refunds: %(count)s, %(total)s", {
                        count: data.refund_count,
                        total: money(data.refund_total),
                    })
                );
                lines.push(_t("Net taken: %s", money(data.net_total)));
            }
            if (data.by_method.length) {
                lines.push("");
                lines.push(_t("By payment method:"));
                for (const [name, amount] of data.by_method) {
                    lines.push(`  ${name}: ${money(amount)}`);
                }
            }
            this.dialog.add(AlertDialog, {
                title: _t("Today's sales — %s", data.date),
                body: lines.join("\n"),
            });
        } catch (error) {
            this.dialog.add(AlertDialog, {
                title: _t("Could not read today's sales"),
                body: error?.data?.message || error?.message || _t("Please try again."),
            });
        }
    },
});
