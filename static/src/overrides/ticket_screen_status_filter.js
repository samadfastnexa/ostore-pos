/** @odoo-module **/

import { patch } from "@web/core/utils/patch";
import { _t } from "@web/core/l10n/translation";
import { TicketScreen } from "@point_of_sale/app/screens/ticket_screen/ticket_screen";
import { fuzzyLookup } from "@point_of_sale/app/utils/fuzzy_lookup";

patch(TicketScreen.prototype, {
    /**
     * Determines whether an order is a Return/Refund.
     */
    isReturnOrder(order) {
        if (!order) return false;
        if (order.is_refund === true || order.isRefund === true) return true;
        if (order.refunded_order_id) return true;
        if (order.return_reason_id) return true;
        if (order.pos_retail_return_unlinked) return true;

        const total = typeof order.get_total_with_tax === "function"
            ? order.get_total_with_tax()
            : (typeof order.priceIncl === "number" ? order.priceIncl : (order.amount_total || 0));
        if (total < -0.005) return true;

        const lines = order.lines || (typeof order.getOrderlines === "function" ? order.getOrderlines() : []);
        if (lines && lines.length > 0) {
            for (const line of lines) {
                const qty = typeof line.get_quantity === "function"
                    ? line.get_quantity()
                    : (typeof line.getQuantity === "function" ? line.getQuantity() : (line.qty || 0));
                if (qty < 0) return true;
            }
        }
        return false;
    },

    /**
     * Determines whether an order is on Customer Credit / Khata.
     */
    isCreditOrder(order) {
        if (!order) return false;
        if (order.pos_retail_on_account && order.pos_retail_on_account > 0.005) return true;
        if (order.pos_retail_credit_manager_id) return true;

        const payments = order.payment_ids || order.paymentlines || [];
        for (const p of payments) {
            const pm = p.payment_method_id || p.payment_method;
            if (pm) {
                if (pm.type === "pay_later") return true;
                const pmName = (pm.name || "").toLowerCase();
                if (/credit|khata|udhar|on account|customer account|pay later|pay_later/i.test(pmName)) {
                    return true;
                }
            }
        }
        return false;
    },

    /**
     * Determines whether an order is fully paid (settled, not credit, not return).
     */
    isPaidOrder(order) {
        if (!order) return false;
        if (this.isReturnOrder(order)) return false;
        if (this.isCreditOrder(order)) return false;
        return Boolean(order.finalized || order.state === "paid" || order.state === "done");
    },

    /**
     * Determines whether an order is Unpaid (active / in-progress on till).
     */
    isUnpaidOrder(order) {
        if (!order) return false;
        if (order.state === "cancel") return false;
        return !order.finalized && order.state !== "paid" && order.state !== "done";
    },

    /**
     * Determines whether an order is linked to a registered customer (not anonymous Walk-in).
     */
    hasActiveCustomer(order) {
        if (!order) return false;
        const partner = order.partner_id || (typeof order.getPartner === "function" ? order.getPartner() : null);
        if (!partner) return false;
        const name = (partner.name || "").trim().toLowerCase();
        if (!name || name === "walk-in customer" || name === "walk in customer") {
            return false;
        }
        return true;
    },

    /**
     * Detailed status descriptor for UI badges and labels.
     */
    getOrderStatusInfo(order) {
        if (this.isReturnOrder(order)) {
            return {
                status: "RETURN",
                label: _t("Return"),
                bgClass: "text-bg-danger",
                icon: "fa-undo",
            };
        }
        if (this.isCreditOrder(order)) {
            return {
                status: "CREDIT",
                label: _t("Credit"),
                bgClass: "text-white",
                style: "background-color: #6f42c1 !important;",
                icon: "fa-book",
            };
        }
        if (this.isPaidOrder(order)) {
            return {
                status: "PAID",
                label: _t("Paid"),
                bgClass: "text-bg-success",
                icon: "fa-check",
            };
        }
        // In-progress / Unpaid
        const screen = order.getScreenData ? order.getScreenData()?.name : "";
        const isPayment = screen === "PaymentScreen";
        return {
            status: "UNPAID",
            label: isPayment ? _t("Unpaid (Payment)") : _t("Unpaid"),
            bgClass: "text-bg-warning text-dark",
            icon: "fa-clock-o",
        };
    },

    /**
     * Override getStatus to return accurate status labels.
     */
    getStatus(order) {
        return this.getOrderStatusInfo(order).label;
    },

    /**
     * Order count for the quick filter pills.
     */
    getOrderCount(filterKey) {
        const orderModel = this.pos.models["pos.order"];
        if (!orderModel) return 0;
        const allOrders = orderModel.getAll ? orderModel.getAll() : (orderModel.records || []);
        const displayedOrders = allOrders.filter(o => o.uiState?.displayed !== false && o.state !== "cancel");

        switch (filterKey) {
            case "ALL":
                return displayedOrders.length;
            case "PAID":
                return displayedOrders.filter(o => this.isPaidOrder(o)).length;
            case "UNPAID":
                return displayedOrders.filter(o => this.isUnpaidOrder(o)).length;
            case "CREDIT":
                return displayedOrders.filter(o => this.isCreditOrder(o)).length;
            case "ACTIVE_CUSTOMER":
                return displayedOrders.filter(o => this.hasActiveCustomer(o)).length;
            case "RETURN":
                return displayedOrders.filter(o => this.isReturnOrder(o)).length;
            default:
                return 0;
        }
    },

    /**
     * Quick filter pills click handler.
     */
    async setPosRetailFilter(filterKey) {
        await this.onFilterSelected(filterKey);
    },

    /**
     * Helper to test if a filter loads server orders.
     */
    _isServerFilter(filter) {
        return ["ALL", "ALL_ORDERS", "SYNCED", "PAID", "CREDIT", "RETURN", "ACTIVE_CUSTOMER"].includes(filter);
    },

    /**
     * Extended filter options for SearchBar dropdown.
     */
    _getFilterOptions() {
        const states = new Map();
        states.set("ALL", { text: _t("All Orders") });
        states.set("PAID", { text: _t("Paid Orders") });
        states.set("UNPAID", { text: _t("Unpaid Orders") });
        states.set("CREDIT", { text: _t("Credit / Khata Orders") });
        states.set("ACTIVE_CUSTOMER", { text: _t("Active Customer Orders") });
        states.set("RETURN", { text: _t("Return / Refund Orders") });
        return states;
    },

    /**
     * Domain filtering for backend search_paid_order_ids.
     */
    _computeSyncedOrdersDomain() {
        const domain = super._computeSyncedOrdersDomain();
        let condition = null;

        if (this.state.filter === "RETURN") {
            condition = ["is_refund", "=", true];
        } else if (this.state.filter === "CREDIT") {
            condition = ["pos_retail_on_account", ">", 0];
        } else if (this.state.filter === "ACTIVE_CUSTOMER") {
            condition = ["partner_id", "!=", false];
        } else if (this.state.filter === "PAID") {
            condition = ["pos_retail_on_account", "=", 0];
        }

        if (condition) {
            if (domain.length > 0) {
                domain.unshift("&");
                domain.splice(1, 0, condition);
            } else {
                domain.push(condition);
            }
        }
        return domain;
    },

    /**
     * On filter change: fetch from server if necessary.
     */
    async onFilterSelected(selectedFilter) {
        this.state.filter = selectedFilter;
        this.pos.screenState.ticketSCreen.totalCount = 0;
        this.pos.screenState.ticketSCreen.offsetByDomain = {};

        if (this._isServerFilter(selectedFilter)) {
            await this._fetchSyncedOrders();
        }
    },

    async onPrevPage() {
        if (this.state.page > 1) {
            this.state.page -= 1;
            if (this._isServerFilter(this.state.filter)) {
                await this._fetchSyncedOrders();
            }
        }
    },

    async onNextPage() {
        if (this.state.page < this.getNbrPages()) {
            this.state.page += 1;
            if (this._isServerFilter(this.state.filter)) {
                await this._fetchSyncedOrders();
            }
        }
    },

    get isOrderSynced() {
        const order = this.getSelectedOrder();
        if (!order) return false;
        return (
            order.finalized &&
            (order.getScreenData().name === "" || this._isServerFilter(this.state.filter))
        );
    },

    /**
     * Main order list filtering based on the active filter.
     */
    getFilteredOrderList() {
        const orderModel = this.pos.models["pos.order"];
        if (!orderModel) return [];

        let orders = [];
        const filter = this.state.filter;

        if (filter === "ALL" || filter === "ALL_ORDERS") {
            orders = orderModel.filter((o) => o.uiState?.displayed !== false && o.state !== "cancel");
        } else if (filter === "PAID" || filter === "SYNCED") {
            orders = orderModel.filter((o) => o.uiState?.displayed !== false && this.isPaidOrder(o));
        } else if (filter === "UNPAID") {
            orders = orderModel.filter((o) => o.uiState?.displayed !== false && this.isUnpaidOrder(o));
        } else if (filter === "CREDIT") {
            orders = orderModel.filter((o) => o.uiState?.displayed !== false && this.isCreditOrder(o));
        } else if (filter === "RETURN") {
            orders = orderModel.filter((o) => o.uiState?.displayed !== false && this.isReturnOrder(o));
        } else if (filter === "ACTIVE_CUSTOMER") {
            orders = orderModel.filter((o) => o.uiState?.displayed !== false && this.hasActiveCustomer(o));
        } else if (filter === "ACTIVE_ORDERS") {
            orders = orderModel.filter(this.activeOrderFilter);
        } else {
            orders = orderModel.filter(this.activeOrderFilter);
            if (filter) {
                orders = orders.filter((order) => {
                    const screen = order.getScreenData ? order.getScreenData() : null;
                    return screen && this._getScreenToStatusMap()[screen.name] === filter;
                });
            }
        }

        if (this.state.search?.searchTerm) {
            const searchField = this._getSearchFields()[this.state.search.fieldName];
            const repr = searchField?.repr;
            if (repr) {
                orders = fuzzyLookup(this.state.search.searchTerm, orders, repr);
            }
        }

        if (this.state.search?.partnerId && this.state.search?.fieldName === "PARTNER") {
            orders = orders.filter((order) => order.partner_id?.id === this.state.search.partnerId);
        }

        if (this.state.selectedPreset) {
            orders = orders.filter((order) => order.preset_id?.id === this.state.selectedPreset.id);
        }

        const sortOrders = (orderList, ascending = false) =>
            orderList.sort((a, b) => {
                const dateA = a.date_order;
                const dateB = b.date_order;

                if (dateA && dateB && !dateA.equals?.(dateB)) {
                    return ascending ? dateA - dateB : dateB - dateA;
                } else {
                    const nameA = parseInt((a.pos_reference || a.name || "").replace(/\D/g, "")) || 0;
                    const nameB = parseInt((b.pos_reference || b.name || "").replace(/\D/g, "")) || 0;
                    return ascending ? nameA - nameB : nameB - nameA;
                }
            });

        this.pos.screenState.ticketSCreen.totalCount = orders.length;

        const isAscending = filter === "ACTIVE_ORDERS" || filter === "UNPAID";
        return sortOrders(orders, isAscending).slice(
            (this.state.page - 1) * this.state.nbrByPage,
            this.state.page * this.state.nbrByPage
        );
    },
});
