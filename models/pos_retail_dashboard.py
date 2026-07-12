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

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------
    @api.model
    def get_dashboard_data(self, period='month'):
        if period not in ('today', 'week', 'month'):
            period = 'month'
        today_local = fields.Date.context_today(self)
        start = self._local_midnight_utc(self._period_start_date(period, today_local))
        trend_start = self._local_midnight_utc(today_local - timedelta(days=29))

        return {
            'period': period,
            'currency_id': self.env.company.currency_id.id,
            'company_name': self.env.company.name,
            'kpis': self._get_kpis(start),
            'sales_trend': self._get_sales_trend(trend_start),
            'payment_breakdown': self._get_payment_breakdown(start),
            'top_products': self._get_top_products(start),
            'low_stock': self._get_low_stock(),
            'expiring_soon': self._get_expiring_soon(),
            'refunds': self._get_refund_stats(start),
        }

    # ------------------------------------------------------------------
    # KPIs
    # ------------------------------------------------------------------
    def _get_kpis(self, start):
        PosOrder = self.env['pos.order']
        base = [('date_order', '>=', start), ('state', 'in', SALE_STATES)]

        sales_group = PosOrder._read_group(base, aggregates=['amount_total:sum', '__count'])
        sales, txns = sales_group[0]
        sales = sales or 0.0
        txns = txns or 0
        avg_basket = (sales / txns) if txns else 0.0

        # gross profit = revenue (excl. tax) - cost of goods sold
        line_group = self.env['pos.order.line']._read_group(
            [('order_id.date_order', '>=', start), ('order_id.state', 'in', SALE_STATES)],
            aggregates=['price_subtotal:sum', 'total_cost:sum'],
        )
        subtotal, cost = line_group[0]
        gross_profit = (subtotal or 0.0) - (cost or 0.0)
        margin_pct = (gross_profit / subtotal * 100) if subtotal else 0.0

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
            'customers': customers,
            'cash_in_drawer': cash_in_drawer,
            'open_sessions': len(open_sessions),
        }

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
    def _get_payment_breakdown(self, start):
        groups = self.env['pos.payment']._read_group(
            domain=[
                ('pos_order_id.date_order', '>=', start),
                ('pos_order_id.state', 'in', SALE_STATES),
            ],
            groupby=['payment_method_id'],
            aggregates=['amount:sum'],
        )
        data = [{'name': method.name, 'amount': amount or 0.0} for method, amount in groups if method]
        data.sort(key=lambda d: -d['amount'])
        return data

    # ------------------------------------------------------------------
    # Top products (by qty, this period)
    # ------------------------------------------------------------------
    def _get_top_products(self, start, limit=8):
        groups = self.env['pos.order.line']._read_group(
            domain=[
                ('order_id.date_order', '>=', start),
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
    def _get_refund_stats(self, start):
        groups = self.env['pos.order']._read_group(
            domain=[
                ('date_order', '>=', start),
                ('state', 'in', SALE_STATES),
                ('amount_total', '<', 0),
            ],
            aggregates=['__count', 'amount_total:sum'],
        )
        count, amount = groups[0]
        return {'count': count or 0, 'amount': amount or 0.0}
