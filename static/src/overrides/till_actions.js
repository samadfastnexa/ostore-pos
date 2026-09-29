/** @odoo-module **/

import { patch } from "@web/core/utils/patch";
import { _t } from "@web/core/l10n/translation";
import { ControlButtons } from "@point_of_sale/app/screens/product_screen/control_buttons/control_buttons";
import { makeAwaitable } from "@point_of_sale/app/utils/make_awaitable_dialog";
import { NumberPopup } from "@point_of_sale/app/components/popups/number_popup/number_popup";
import { AlertDialog } from "@web/core/confirmation_dialog/confirmation_dialog";
import { ThermalLabelPopup } from "@pos_retail/overrides/thermal_label_popup";
import { PosRetailStockModal } from "@pos_retail/overrides/stock_modal";
import { PosRetailQuotationModal } from "@pos_retail/overrides/quotation_modal";

patch(ControlButtons.prototype, {
    get posRetailCanAdjustStock() {
        return Boolean(this.pos.getCashier()?._can_stock_adjust);
    },

    get posRetailCanSeeDailySales() {
        return Boolean(this.pos.getCashier()?._can_daily_sales);
    },

    get posRetailStockTarget() {
        return this.pos.getOrder()?.getSelectedOrderline()?.product_id;
    },

    /** Open the comprehensive Store Stock Browser & Adjustment Modal */
    async onClickStockInventory() {
        this.props.close?.();
        this.dialog.add(PosRetailStockModal, {});
    },

    /** Turn the current POS cart directly into an official Sales Quotation */
    async onClickMakeQuotation() {
        const order = this.pos.getOrder();
        const lines = (order?.getOrderlines() || []).filter(
            (l) => !l.isDiscountLine && l.getQuantity() > 0
        );
        if (!lines.length) {
            this.dialog.add(AlertDialog, {
                title: _t("Cart is Empty"),
                body: _t(
                    "Please add at least one product to the order first, then click Make Quotation."
                ),
            });
            return;
        }

        let partner = order.getPartner();
        if (!partner) {
            partner = await this.pos.selectPartner();
            if (!partner) {
                return;
            }
        }

        try {
            const payload = {
                partner_id: partner.id,
                approved_by: this.pos.getCashier()?.id || false,
                lines: lines.map((l) => ({
                    product_id: l.product_id.id,
                    qty: l.getQuantity(),
                    price_unit: l.price_unit,
                    discount: l.discount || 0,
                    tax_ids: (l.tax_ids || []).map((t) => t.id),
                })),
            };
            const res = await this.pos.data.call("sale.order", "_pos_retail_create_quotation", [
                payload,
            ]);

            this.pos.addNewOrder();
            this.pos.removeOrder(order, false);
            this.props.close?.();

            this.notification.add(
                _t("Quotation %(name)s created successfully for %(partner)s!", {
                    name: res.name,
                    partner: res.partner_name,
                }),
                { type: "success" }
            );
        } catch (err) {
            this.dialog.add(AlertDialog, {
                title: _t("Could not save quotation"),
                body: err?.data?.message || err?.message || _t("An error occurred."),
            });
        }
    },

    /** Open the Quotations History & Settle modal to view, settle, or duplicate quotes */
    async onClickQuotationHistory() {
        this.props.close?.();
        this.dialog.add(PosRetailQuotationModal, {});
    },

    async onClickAdjustStock() {
        const product = this.posRetailStockTarget;
        if (!product) {
            // If no product is selected in cart, open the full stock browser instead!
            return this.onClickStockInventory();
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

    async onClickPrintThermalLabel() {
        const product = this.posRetailStockTarget;
        if (!product) {
            this.dialog.add(AlertDialog, {
                title: _t("Select a Product"),
                body: _t(
                    "Please select or add a product in the order first to print its thermal barcode label."
                ),
            });
            return;
        }

        this.dialog.add(ThermalLabelPopup, {
            product: product,
        });
    },
});
