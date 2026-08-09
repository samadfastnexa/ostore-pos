from datetime import datetime, time, timedelta

import pytz

from odoo import _, api, fields, models
from odoo.exceptions import AccessError

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

    def _previous_comparable_bounds(self, period, start, end, today_local):
        """An honest baseline for the trend indicator: the same elapsed
        duration, one period back — not the full previous period (which would
        make an in-progress "Today"/"This Month" look artificially down)."""
        if end:
            length = end - start
            return start - length, start
        now_utc = fields.Datetime.now()
        elapsed = max(now_utc - start, timedelta(seconds=1))
        if period == 'today':
            prev_start = start - timedelta(days=1)
        elif period == 'week':
            prev_start = start - timedelta(days=7)
        else:  # month
            prev_month_date = (today_local.replace(day=1) - timedelta(days=1)).replace(day=1)
            prev_start = self._local_midnight_utc(prev_month_date)
        return prev_start, prev_start + elapsed

    def _pct_change(self, current, previous):
        if not previous:
            return None  # no baseline to compare against -- don't show a misleading 0%/inf swing
        return (current - previous) / abs(previous) * 100

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------
    @api.model
    def get_dashboard_data(self, period='month', date_from=None, date_to=None):
        # This model is abstract: it owns no table, so ir.model.access never
        # runs for it and the ACL layer that protects every other model here is
        # simply absent. The menu is restricted to POS managers
        # (pos_retail_dashboard_views.xml), but a menu only hides a button --
        # any logged-in user, a cashier included, can still reach this method
        # over /web/dataset/call_kw and read the whole financial picture:
        # takings, margin, cost of goods sold, expenses, stock valuation.
        # Re-state the menu's restriction where it is actually enforceable.
        if not self.env.user.has_group('point_of_sale.group_pos_manager'):
            raise AccessError(_(
                "The Point of Sale dashboard is available to Point of Sale "
                "managers only."
            ))
        if period not in ('today', 'week', 'month', 'custom'):
            period = 'month'
        today_local = fields.Date.context_today(self)
        start, end = self._resolve_period_bounds(period, date_from, date_to, today_local)
        trend_start = self._local_midnight_utc(today_local - timedelta(days=29))

        kpis = self._get_kpis(start, end)
        kpis.update(self._get_inventory_kpis())
        kpis.update(self._get_expense_kpis())
        kpis.update(self._get_stock_flow_today())
        kpis.update(self._get_damaged_expired_kpis(start, end))
        kpis.update(self._get_turnover_kpis(start, end))
        kpis.update(self._get_reorder_cost())
        movement = self._get_movement_analysis(start, end)
        kpis['dead_stock_count'] = movement['dead_stock_count']
        kpis['dead_stock_value'] = movement['dead_stock_value']

        return {
            'period': period,
            # The resolved window, so a card's drill-through opens exactly the
            # records that produced the figure rather than re-deriving dates
            # client-side and drifting from them.
            'period_start': fields.Datetime.to_string(start) if start else False,
            'period_end': fields.Datetime.to_string(end) if end else False,
            'drill': self._get_drill_targets(start, end, movement),
            'currency_id': self.env.company.currency_id.id,
            'company_name': self.env.company.name,
            'kpis': kpis,
            'trend': self._get_trend(period, start, end, today_local, kpis),
            'sales_trend': self._get_sales_trend(trend_start),
            'payment_breakdown': self._get_payment_breakdown(start, end),
            'top_products': self._get_top_products(start, end),
            'sales_by_cashier': self._get_sales_by_cashier(start, end),
            'top_customers': self._get_top_customers(start, end),
            'low_stock': self._get_low_stock(),
            'expiring_soon': self._get_expiring_soon(),
            'fast_movers': movement['fast_movers'],
            'slow_movers': movement['slow_movers'],
            'dead_stock': movement['dead_stock'],
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
    # Trend (small up/down indicator on the headline KPI tiles)
    # ------------------------------------------------------------------
    def _get_trend(self, period, start, end, today_local, kpis):
        prev_start, prev_end = self._previous_comparable_bounds(period, start, end, today_local)
        prev_kpis = self._get_kpis(prev_start, prev_end)
        return {
            'sales_pct': self._pct_change(kpis['sales'], prev_kpis['sales']),
            'transactions_pct': self._pct_change(kpis['transactions'], prev_kpis['transactions']),
            'gross_profit_pct': self._pct_change(kpis['gross_profit'], prev_kpis['gross_profit']),
            'net_sales_pct': self._pct_change(kpis['net_sales'], prev_kpis['net_sales']),
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
    # Record ids behind each figure, so every card can be opened
    # ------------------------------------------------------------------
    def _get_drill_targets(self, start, end, movement):
        """Ids the dashboard cards drill into.

        Sent as explicit id lists rather than domains the client rebuilds:
        several figures (dead stock, expired lots, products in POS) come from
        python-side filtering that no simple domain reproduces, and a card
        that opened a *slightly* different set than the number it sits under
        would quietly undermine trust in the whole dashboard.
        """
        Product = self.env['product.product']
        storable = Product.search([('is_storable', '=', True), ('available_in_pos', '=', True)])
        quants = self.env['stock.quant']._read_group(
            [('product_id', 'in', storable.ids), ('location_id.usage', '=', 'internal')],
            groupby=['product_id'], aggregates=['quantity:sum'],
        )
        qty_by_product = {product: qty or 0.0 for product, qty in quants}

        expired_lot_ids = []
        Lot = self.env['stock.lot']
        if 'expiration_date' in Lot._fields:
            now = fields.Datetime.now()
            expired_lot_ids = [
                lot.id for lot in Lot.search(
                    [('expiration_date', '!=', False), ('expiration_date', '<', now)])
                if (lot.product_qty or 0.0) > 0
            ]

        reorder_ids = [
            op.id for op in self.env['stock.warehouse.orderpoint'].search([])
            if op.qty_on_hand <= op.product_min_qty
            and (op.product_max_qty or op.product_min_qty) - op.qty_on_hand > 0
        ]

        today_start = self._local_midnight_utc(fields.Date.context_today(self))
        return {
            'pos_product_ids': storable.ids,
            'out_of_stock_ids': [p.id for p in storable if qty_by_product.get(p, 0.0) <= 0],
            'in_stock_ids': [p.id for p in storable if qty_by_product.get(p, 0.0) > 0],
            'negative_stock_ids': [p.id for p in storable if qty_by_product.get(p, 0.0) < 0],
            'dead_stock_ids': movement['dead_stock_all_ids'],
            'fast_mover_ids': movement['fast_mover_all_ids'],
            'slow_mover_ids': movement['slow_mover_all_ids'],
            'expired_lot_ids': expired_lot_ids,
            'reorder_ids': reorder_ids,
            'today_start': fields.Datetime.to_string(today_start),
        }

    # ------------------------------------------------------------------
    # Stock movement today (goods physically received vs shipped out)
    # ------------------------------------------------------------------
    def _get_stock_flow_today(self):
        """Quantity and value moved in and out of internal stock today.

        Measured on stock.move.line (what actually moved) rather than on
        pickings, so a partially received delivery counts what arrived rather
        than the whole order. Internal transfers are excluded on purpose: a
        move between two of the shop's own locations is not stock coming in
        or going out.
        """
        Move = self.env['stock.move.line']
        today_start = self._local_midnight_utc(fields.Date.context_today(self))
        base = [('state', '=', 'done'), ('date', '>=', today_start)]

        def flow(domain):
            qty = value = 0.0
            for line in Move.search(domain):
                moved = line.quantity or 0.0
                qty += moved
                value += moved * (line.product_id.standard_price or 0.0)
            return {'qty': qty, 'value': value}

        stock_in = flow(base + [
            ('location_id.usage', 'not in', ('internal', 'transit')),
            ('location_dest_id.usage', '=', 'internal'),
        ])
        stock_out = flow(base + [
            ('location_id.usage', '=', 'internal'),
            ('location_dest_id.usage', 'not in', ('internal', 'transit')),
        ])
        return {
            'stock_in_qty_today': stock_in['qty'],
            'stock_in_value_today': stock_in['value'],
            'stock_out_qty_today': stock_out['qty'],
            'stock_out_value_today': stock_out['value'],
        }

    # ------------------------------------------------------------------
    # Damaged (scrapped) and expired stock
    # ------------------------------------------------------------------
    def _get_damaged_expired_kpis(self, start, end=None):
        """Damaged = stock scrapped in the period. Expired = what is sitting
        in stock today past its expiry date, which is a standing loss rather
        than a period figure."""
        damaged_qty = damaged_value = 0.0
        Scrap = self.env['stock.scrap']
        domain = [('state', '=', 'done')] + self._date_domain('date_done', start, end)
        for scrap in Scrap.search(domain):
            qty = scrap.scrap_qty or 0.0
            damaged_qty += qty
            damaged_value += qty * (scrap.product_id.standard_price or 0.0)

        expired_qty = expired_value = 0.0
        expired_lots = 0
        Lot = self.env['stock.lot']
        if 'expiration_date' in Lot._fields:
            now = fields.Datetime.now()
            for lot in Lot.search([('expiration_date', '!=', False),
                                   ('expiration_date', '<', now)]):
                qty = lot.product_qty or 0.0
                if qty > 0:
                    expired_lots += 1
                    expired_qty += qty
                    expired_value += qty * (lot.product_id.standard_price or 0.0)

        return {
            'damaged_qty': damaged_qty,
            'damaged_value': damaged_value,
            'expired_qty': expired_qty,
            'expired_value': expired_value,
            'expired_lot_count': expired_lots,
        }

    # ------------------------------------------------------------------
    # Stock turnover and the cost of restocking what is low
    # ------------------------------------------------------------------
    def _get_turnover_kpis(self, start, end=None):
        """Turnover = cost of goods sold in the period / stock value at cost.

        The textbook denominator is AVERAGE inventory over the period; the
        value here is today's closing stock, because Odoo does not keep a
        cheap historical valuation series and reconstructing one would make
        the dashboard slow. Stated plainly rather than passed off as the
        classic ratio: it answers "how many times over did I sell my current
        shelf" which is the question a shopkeeper actually asks.
        """
        lines = self.env['pos.order.line'].search([
            ('order_id.state', 'in', ('paid', 'done', 'invoiced')),
        ] + self._date_domain('order_id.date_order', start, end))
        cogs = sum(
            (line.qty or 0.0) * (line.product_id.standard_price or 0.0)
            for line in lines if (line.qty or 0.0) > 0
        )
        stock_value = sum(
            quant.quantity * (quant.product_id.standard_price or 0.0)
            for quant in self.env['stock.quant'].search(
                [('location_id.usage', '=', 'internal')])
        )
        return {
            'cogs_period': cogs,
            'stock_turnover': (cogs / stock_value) if stock_value else 0.0,
        }

    def _get_reorder_cost(self):
        """What it would cost to bring every low product back to its maximum.

        Uses the reordering rules the shop has already set, so the figure is
        grounded in its own policy rather than a guess.
        """
        total = 0.0
        products = 0
        for op in self.env['stock.warehouse.orderpoint'].search([]):
            on_hand = op.qty_on_hand
            if on_hand > op.product_min_qty:
                continue
            target = op.product_max_qty or op.product_min_qty
            missing = target - on_hand
            if missing <= 0:
                continue
            products += 1
            total += missing * (op.product_id.standard_price or 0.0)
        return {'reorder_cost': total, 'reorder_product_count': products}

    # ------------------------------------------------------------------
    # Movement analysis: what sells fast, what sells slowly, what never sells
    # ------------------------------------------------------------------
    def _get_movement_analysis(self, start, end=None, limit=8):
        """Rank products by how much stock they turned over in the period.

        Dead stock is the important one: products holding money on the shelf
        with NO sales at all in the period. Slow movers did sell, just barely,
        so they are a different problem and kept separate.
        """
        sold = {}
        lines = self.env['pos.order.line'].search([
            ('order_id.state', 'in', ('paid', 'done', 'invoiced')),
        ] + self._date_domain('order_id.date_order', start, end))
        for line in lines:
            qty = line.qty or 0.0
            if qty <= 0 or not line.product_id:
                continue
            stat = sold.setdefault(line.product_id, {'qty': 0.0, 'revenue': 0.0})
            stat['qty'] += qty
            stat['revenue'] += line.price_subtotal_incl or 0.0

        stocked = self.env['product.product'].search([
            ('is_storable', '=', True), ('available_in_pos', '=', True),
        ])
        quants = self.env['stock.quant']._read_group(
            [('product_id', 'in', stocked.ids), ('location_id.usage', '=', 'internal')],
            groupby=['product_id'], aggregates=['quantity:sum'],
        )
        on_hand = {product: qty or 0.0 for product, qty in quants}

        def row(product, stat, qty_on_hand):
            return {
                'product_id': product.id,
                'name': product.display_name,
                'qty_sold': stat['qty'],
                'revenue': stat['revenue'],
                'on_hand': qty_on_hand,
                'stock_value': qty_on_hand * (product.standard_price or 0.0),
            }

        movers = [row(p, s, on_hand.get(p, 0.0)) for p, s in sold.items()]
        movers.sort(key=lambda r: (-r['qty_sold'], -r['revenue']))

        dead = [
            row(p, {'qty': 0.0, 'revenue': 0.0}, on_hand.get(p, 0.0))
            for p in stocked
            if p not in sold and on_hand.get(p, 0.0) > 0
        ]
        dead.sort(key=lambda r: -r['stock_value'])

        # Slow movers must still be products that SOLD; anything with no
        # sales belongs in dead stock, not at the bottom of this list.
        slow = [r for r in reversed(movers) if r['qty_sold'] > 0]
        return {
            'fast_movers': movers[:limit],
            'slow_movers': slow[:limit],
            'dead_stock': dead[:limit],
            'dead_stock_count': len(dead),
            'dead_stock_value': sum(r['stock_value'] for r in dead),
            # Full id lists for the drill-throughs: the panels show the worst
            # few, but clicking the headline figure must open everything it
            # counted, not just the visible rows.
            'dead_stock_all_ids': [r['product_id'] for r in dead],
            'fast_mover_all_ids': [r['product_id'] for r in movers],
            'slow_mover_all_ids': [r['product_id'] for r in slow],
        }

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
