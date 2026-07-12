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
        this.state = useState({ loading: true, period: "month", data: null });
        onWillStart(() => this.load());
    }

    async load() {
        this.state.loading = true;
        this.state.data = await this.orm.call("pos.retail.dashboard", "get_dashboard_data", [
            this.state.period,
        ]);
        this.state.loading = false;
    }

    setPeriod(period) {
        if (period === this.state.period) {
            return;
        }
        this.state.period = period;
        this.load();
    }

    get periodLabel() {
        return { today: "Today", week: "This Week", month: "This Month" }[this.state.period];
    }

    // --- formatting -----------------------------------------------------
    money(value) {
        return formatMonetary(value ?? 0, { currencyId: this.state.data.currency_id });
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

    refresh() {
        this.load();
    }
}

registry.category("actions").add("pos_retail_dashboard", PosRetailDashboard);
