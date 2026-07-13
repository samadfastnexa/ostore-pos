from datetime import datetime, time, timedelta

import pytz

from odoo import api, fields, models

SALE_STATES = ('paid', 'done')


class PosRetailDashboard(models.AbstractModel):
    _name = 'pos.retail.dashboard'
    _description = "POS Retail Dashboard Data Provider"

    # ------------------------------------------------------------------
    # Date helpers (timezone-aware period boundaries)
    # ------------------------------------------------------------------
    def _tz(self):
        return pytz.timezone(self.env.user.tz or 'UTC')

    def _local_midnight_utc(self, local_date):
        tz = self._tz()
        local_dt = tz.localize(datetime.combine(local_date, time.min))
        return local_dt.astimezone(pytz.utc).replace(tzinfo=None)

    def _period_start_date(self, period, today_local):
        if period == 'today':
            return today_local
        if period == 'week':
            return today_local - timedelta(days=today_local.weekday())
        return today_local.replace(day=1)  # month (default)

    def _resolve_period_bounds(self, period, date_from, date_to, today_local):
        if period == 'custom':
            d_from = fields.Date.from_string(date_from) if date_from else today_local
            d_to = fields.Date.from_string(date_to) if date_to else today_local
            if d_from > d_to:
                d_from, d_to = d_to, d_from
            return self._local_midnight_utc(d_from), self._local_midnight_utc(d_to + timedelta(days=1))
        return self._local_midnight_utc(self._period_start_date(period, today_local)), None

    def _date_domain(self, field, start, end):
        domain = [(field, '>=', start)]
        if end:
            domain.append((field, '<', end))
        return domain

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------
    @api.model
    def get_dashboard_data(self, period='month', date_from=None, date_to=None):
        if period not in ('today', 'week', 'month', 'custom'):
            period = 'month'
        today_local = fields.Date.context_today(self)
        start, end = self._resolve_period_bounds(period, date_from, date_to, today_local)
        trend_start = self._local_midnight_utc(today_local - timedelta(days=29))

        kpis = self._get_kpis(start, end)
        kpis.update(self._get_inventory_kpis())
        kpis.update(self._get_expense_kpis())

        return {
            'period': period,
            'currency_id': self.env.company.currency_id.id,
            'company_name': self.env.company.name,
            'kpis': kpis,
            'sales_trend': self._get_sales_trend(trend_start),
            'payment_breakdown': self._get_payment_breakdown(start, end),
            'top_products': self._get_top_products(start, end),
            'sales_by_cashier': self._get_sales_by_cashier(start, end),
            'top_customers': self._get_top_customers(start, end),
            'low_stock': self._get_low_stock(),
            'expiring_soon': self._get_expiring_soon(),
            'refunds': self._get_refund_stats(start, end),
        }

    # ------------------------------------------------------------------
    # KPIs
    # ------------------------------------------------------------------
    def _get_kpis(self, start, end=None):
        PosOrder = self.env['pos.order']
        base = self._date_domain('date_order', start, end) + [('state', 'in', SALE_STATES)]

        sales_group = PosOrder._read_group(
            base, aggregates=['amount_total:sum', 'amount_tax:sum', '__count']
        )
        sales, tax, txns = sales_group[0]
        sales = sales or 0.0
        taxes_collected = tax or 0.0
        txns = txns or 0
        avg_basket = (sales / txns) if txns else 0.0

        # gross profit = revenue (excl. tax) - cost of goods sold
        line_group = self.env['pos.order.line']._read_group(
            self._date_domain('order_id.date_order', start, end) + [('order_id.state', 'in', SALE_STATES)],
            aggregates=['price_subtotal:sum', 'total_cost:sum'],
        )
        subtotal, cost = line_group[0]
        net_sales = subtotal or 0.0
        cogs = cost or 0.0
        gross_profit = net_sales - cogs
        margin_pct = (gross_profit / net_sales * 100) if net_sales else 0.0

        # discounts given, sourced from the native report (currency-rate-aware)
        discount_group = self.env['report.pos.order']._read_group(
            self._date_domain('date', start, end) + [('state', 'in', SALE_STATES)],
            aggregates=['total_discount:sum'],
        )
        discounts_given = discount_group[0][0] or 0.0

        # distinct customers served
        cust_group = PosOrder._read_group(base + [('partner_id', '!=', False)], groupby=['partner_id'])
        customers = len(cust_group)

        open_sessions = self.env['pos.session'].search([('state', '=', 'opened')])
        cash_in_drawer = sum(open_sessions.mapped('cash_register_balance_end'))

        return {
            'sales': sales,
            'transactions': txns,
            'avg_basket': avg_basket,
            'gross_profit': gross_profit,
            'margin_pct': margin_pct,
            'cogs': cogs,
            'net_sales': net_sales,
            'taxes_collected': taxes_collected,
            'discounts_given': discounts_given,
            'customers': customers,
            'cash_in_drawer': cash_in_drawer,
            'open_sessions': len(open_sessions),
        }

    # ------------------------------------------------------------------
    # Inventory KPIs (point-in-time snapshot, not period-scoped)
    # ------------------------------------------------------------------
    def _get_inventory_kpis(self):
        Product = self.env['product.product']
        storable = Product.search([('is_storable', '=', True), ('available_in_pos', '=', True)])
        quant_groups = self.env['stock.quant']._read_group(
            [('product_id', 'in', storable.ids), ('location_id.usage', '=', 'internal')],
            groupby=['product_id'],
            aggregates=['quantity:sum'],
        )
        qty_by_product = {product: qty or 0.0 for product, qty in quant_groups}
        return {
            'total_products': len(storable),
            'total_stock_qty': sum(qty_by_product.values()),
            'inventory_value_cost': sum(qty * p.standard_price for p, qty in qty_by_product.items()),
            'inventory_value_selling': sum(qty * p.list_price for p, qty in qty_by_product.items()),
            'out_of_stock_count': sum(1 for p in storable if qty_by_product.get(p, 0.0) <= 0),
            'negative_stock_count': sum(1 for p in storable if qty_by_product.get(p, 0.0) < 0),
        }

    # ------------------------------------------------------------------
    # Expense KPIs (fixed Today / This Month, independent of the period filter)
    # ------------------------------------------------------------------
    def _get_expense_kpis(self):
        Expense = self.env['pos.retail.expense']
        today_local = fields.Date.context_today(self)
        month_start = today_local.replace(day=1)
        today_amt = Expense._read_group(
            [('date', '=', today_local)], aggregates=['amount:sum']
        )[0][0] or 0.0
        month_amt = Expense._read_group(
            [('date', '>=', month_start), ('date', '<=', today_local)], aggregates=['amount:sum']
        )[0][0] or 0.0
        return {'expenses_today': today_amt, 'expenses_month': month_amt}

    # ------------------------------------------------------------------
    # Sales by cashier (this period)
    # ------------------------------------------------------------------
    def _get_sales_by_cashier(self, start, end=None, limit=8):
        base = self._date_domain('date_order', start, end) + [('state', 'in', SALE_STATES)]
        groups = self.env['pos.order']._read_group(
            base + [('employee_id', '!=', False)],
            groupby=['employee_id'],
            aggregates=['amount_total:sum', '__count'],
            order='amount_total:sum desc',
            limit=limit,
        )
        return [{
            'employee_id': employee.id,
            'name': employee.name,
            'sales': sales or 0.0,
            'transactions': count or 0,
        } for employee, sales, count in groups]

    # ------------------------------------------------------------------
    # Top customers (this period)
    # ------------------------------------------------------------------
    def _get_top_customers(self, start, end=None, limit=8):
        base = self._date_domain('date_order', start, end) + [('state', 'in', SALE_STATES)]
        groups = self.env['pos.order']._read_group(
            base + [('partner_id', '!=', False)],
            groupby=['partner_id'],
            aggregates=['amount_total:sum', '__count'],
            order='amount_total:sum desc',
            limit=limit,
        )
        return [{
            'partner_id': partner.id,
            'name': partner.display_name,
            'sales': sales or 0.0,
            'transactions': count or 0,
        } for partner, sales, count in groups]

    # ------------------------------------------------------------------
    # Sales trend (30 days, gap-filled)
    # ------------------------------------------------------------------
    def _get_sales_trend(self, trend_start):
        groups = self.env['pos.order']._read_group(
            domain=[('date_order', '>=', trend_start), ('state', 'in', SALE_STATES)],
            groupby=['date_order:day'],
            aggregates=['amount_total:sum'],
        )
        by_day = {fields.Date.to_string(day): (total or 0.0) for day, total in groups}
        today_local = fields.Date.context_today(self)
        series = []
        for i in range(30):
            d = today_local - timedelta(days=29 - i)
            key = fields.Date.to_string(d)
            series.append({'date': key, 'total': by_day.get(key, 0.0)})
        return series

    # ------------------------------------------------------------------
    # Payment method breakdown (categorical)
    # ------------------------------------------------------------------
    def _get_payment_breakdown(self, start, end=None):
        groups = self.env['pos.payment']._read_group(
            domain=self._date_domain('pos_order_id.date_order', start, end)
            + [('pos_order_id.state', 'in', SALE_STATES)],
            groupby=['payment_method_id'],
            aggregates=['amount:sum'],
        )
        data = [{'name': method.name, 'amount': amount or 0.0} for method, amount in groups if method]
        data.sort(key=lambda d: -d['amount'])
        return data

    # ------------------------------------------------------------------
    # Top products (by qty, this period)
    # ------------------------------------------------------------------
    def _get_top_products(self, start, end=None, limit=8):
        groups = self.env['pos.order.line']._read_group(
            domain=self._date_domain('order_id.date_order', start, end) + [
                ('order_id.state', 'in', SALE_STATES),
                ('qty', '>', 0),
            ],
            groupby=['product_id'],
            aggregates=['qty:sum', 'price_subtotal_incl:sum'],
            order='qty:sum desc',
            limit=limit,
        )
        return [{
            'product_id': product.id,
            'name': product.display_name,
            'qty': qty or 0.0,
            'revenue': revenue or 0.0,
        } for product, qty, revenue in groups]

    # ------------------------------------------------------------------
    # Low stock (products at/below their reorder minimum) — status
    # ------------------------------------------------------------------
    def _get_low_stock(self, limit=8):
        rows = []
        for op in self.env['stock.warehouse.orderpoint'].search([]):
            if op.qty_on_hand <= op.product_min_qty:
                rows.append({
                    'product_id': op.product_id.id,
                    'name': op.product_id.display_name,
                    'on_hand': op.qty_on_hand,
                    'min': op.product_min_qty,
                })
        rows.sort(key=lambda r: r['on_hand'])
        return rows[:limit]

    # ------------------------------------------------------------------
    # Expiring soon (lots expiring within 30 days, still on hand) — status
    # ------------------------------------------------------------------
    def _get_expiring_soon(self, days=30, limit=8):
        Lot = self.env['stock.lot']
        if 'expiration_date' not in Lot._fields:
            return []
        limit_dt = fields.Datetime.now() + timedelta(days=days)
        today_local = fields.Date.context_today(self)
        rows = []
        for lot in Lot.search([('expiration_date', '!=', False), ('expiration_date', '<=', limit_dt)]):
            if lot.product_qty > 0:
                days_left = (lot.expiration_date.date() - today_local).days
                rows.append({
                    'name': lot.product_id.display_name,
                    'lot': lot.name,
                    'expiration_date': fields.Date.to_string(lot.expiration_date.date()),
                    'days_left': days_left,
                    'qty': lot.product_qty,
                })
        rows.sort(key=lambda r: r['days_left'])
        return rows[:limit]

    # ------------------------------------------------------------------
    # Refund stats
    # ------------------------------------------------------------------
    def _get_refund_stats(self, start, end=None):
        groups = self.env['pos.order']._read_group(
            domain=self._date_domain('date_order', start, end) + [
                ('state', 'in', SALE_STATES),
                ('amount_total', '<', 0),
            ],
            aggregates=['__count', 'amount_total:sum'],
        )
        count, amount = groups[0]
        return {'count': count or 0, 'amount': amount or 0.0}
