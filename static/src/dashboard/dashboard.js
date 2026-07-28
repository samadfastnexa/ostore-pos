/** @odoo-module **/

import { Component, useState, onWillStart } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { formatMonetary } from "@web/views/fields/formatters";

// Fixed categorical order — hues assigned by index, never cycled/repainted.
const CATEGORICAL = ["#4f46e5", "#0ea5e9", "#10b981", "#f59e0b", "#f43f5e", "#8b5cf6", "#14b8a6", "#64748b"];

export class PosRetailDashboard extends Component {
    static template = "pos_retail.Dashboard";
    static props = { "*": true };

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        const today = new Date().toISOString().slice(0, 10);
        this.today = today;
        this.state = useState({
            loading: true,
            period: "month",
            showCustom: false,
            dateFrom: today,
            dateTo: today,
            data: null,
            trend: {},
        });
        onWillStart(() => this.load());
    }

    async load() {
        this.state.loading = true;
        const kwargs = this.state.period === "custom"
            ? { date_from: this.state.dateFrom, date_to: this.state.dateTo }
            : {};
        this.state.data = await this.orm.call(
            "pos.retail.dashboard", "get_dashboard_data", [this.state.period], kwargs
        );
        this.state.trend = this.state.data.trend || {};
        this.state.loading = false;
    }

    setPeriod(period) {
        this.state.showCustom = false;
        if (period === this.state.period) {
            return;
        }
        this.state.period = period;
        this.load();
    }

    toggleCustom() {
        this.state.showCustom = !this.state.showCustom;
    }

    applyCustom() {
        this.state.period = "custom";
        this.state.showCustom = false;
        this.load();
    }

    get periodLabel() {
        if (this.state.period === "custom") {
            return `${this.shortDate(this.state.dateFrom)} – ${this.shortDate(this.state.dateTo)}`;
        }
        return { today: "Today", week: "This Week", month: "This Month" }[this.state.period];
    }

    // --- formatting -----------------------------------------------------
    money(value) {
        return formatMonetary(value ?? 0, { currencyId: this.state.data.currency_id });
    }

    /** Quantities are counts of goods, not money: no currency, no decimals
     *  unless the number actually has them. */
    qtyLabel(value) {
        const qty = Math.round((value ?? 0) * 100) / 100;
        return `${qty} unit(s)`;
    }

    /** Turnover reads as "1.8x": how many times the current shelf was sold
     *  over during the period. */
    get turnoverLabel() {
        const t = this.state.data?.kpis?.stock_turnover ?? 0;
        return `${(Math.round(t * 100) / 100).toFixed(2)}x`;
    }

    shortDate(isoDate) {
        const d = new Date(isoDate + "T00:00:00");
        return d.toLocaleDateString(undefined, { month: "short", day: "numeric" });
    }

    color(i) {
        return CATEGORICAL[i % CATEGORICAL.length];
    }

    // --- sales trend chart geometry (dependency-free inline SVG) ---------
    get chart() {
        const series = this.state.data.sales_trend || [];
        const width = 720;
        const height = 200;
        const pad = { top: 10, right: 10, bottom: 22, left: 10 };
        const innerW = width - pad.left - pad.right;
        const innerH = height - pad.top - pad.bottom;
        const max = Math.max(1, ...series.map((p) => p.total));
        const n = series.length || 1;
        const gap = 4;
        const barW = Math.max(1, innerW / n - gap);
        const bars = series.map((p, i) => {
            const h = (p.total / max) * innerH;
            return {
                x: pad.left + i * (innerW / n),
                y: pad.top + (innerH - h),
                w: barW,
                h,
                total: p.total,
                date: p.date,
                label: this.shortDate(p.date),
            };
        });
        return { width, height, bars, max, baseline: pad.top + innerH };
    }

    // --- payment breakdown (categorical bars with direct labels) --------
    get payments() {
        const rows = this.state.data.payment_breakdown || [];
        const total = rows.reduce((s, r) => s + r.amount, 0) || 1;
        return rows.map((r, i) => ({
            name: r.name,
            amount: r.amount,
            pct: (r.amount / total) * 100,
            color: this.color(i),
        }));
    }

    // --- trend indicator (up/down vs the same elapsed time, one period back)
    trendClass(pct) {
        if (pct === null || pct === undefined) {
            return "o_trend_flat";
        }
        return pct >= 0 ? "o_trend_up" : "o_trend_down";
    }

    trendIcon(pct) {
        if (pct === null || pct === undefined) {
            return "fa-minus";
        }
        return pct >= 0 ? "fa-arrow-up" : "fa-arrow-down";
    }

    trendLabel(pct) {
        if (pct === null || pct === undefined) {
            return "no prior data";
        }
        return `${Math.abs(pct).toFixed(1)}%`;
    }

    expiryClass(daysLeft) {
        if (daysLeft <= 3) {
            return "o_status_critical";
        }
        if (daysLeft <= 10) {
            return "o_status_serious";
        }
        return "o_status_warning";
    }

    // --- drill-downs ----------------------------------------------------
    openOrders(domain, name) {
        this.action.doAction({
            type: "ir.actions.act_window",
            name,
            res_model: "pos.order",
            views: [[false, "list"], [false, "form"]],
            domain: domain || [],
        });
    }

    openProduct(productId) {
        this.action.doAction({
            type: "ir.actions.act_window",
            res_model: "product.product",
            res_id: productId,
            views: [[false, "form"]],
        });
    }

    openCashier(employeeId, name) {
        this.openOrders([["employee_id", "=", employeeId], ["state", "in", ["paid", "done"]]], name);
    }

    openCustomer(partnerId, name) {
        this.openOrders([["partner_id", "=", partnerId], ["state", "in", ["paid", "done"]]], name);
    }

    openNegativeStock() {
        this.action.doAction({
            type: "ir.actions.act_window",
            name: "Negative Stock Warnings",
            res_model: "pos.retail.inventory.movement",
            views: [[false, "list"], [false, "form"]],
            domain: [["has_negative_stock_warning", "=", true]],
        });
    }

    openExpenses(domain, name) {
        this.action.doAction({
            type: "ir.actions.act_window",
            name,
            res_model: "pos.retail.expense",
            views: [[false, "list"], [false, "form"]],
            domain: domain || [],
        });
    }

    openRegister() {
        // The native session-management kanban (New Session / Resume) — its
        // menu entry is hidden so this dashboard stays the single "Dashboard".
        this.action.doAction("point_of_sale.action_pos_config_kanban");
    }

    refresh() {
        this.load();
    }
}

registry.category("actions").add("pos_retail_dashboard", PosRetailDashboard);
