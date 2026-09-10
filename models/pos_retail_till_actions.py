from odoo import _, api, fields, models
from odoo.exceptions import UserError


class PosSessionTillActions(models.Model):
    """Jobs a cashier does at the counter that are not selling.

    The shop's case for putting these in the till rather than the back office
    was practical and correct: the counter is busy, the customer is waiting,
    and the person serving is not going to open a second browser and sign in.

    WHOSE PERMISSION IS CHECKED, and why it is not the obvious one. Every call
    from a till arrives as the TILL ACCOUNT, because that is the one shared
    login the device is signed in as. Checking the caller would give the same
    answer for every person who ever stands at that counter. So each method
    checks the EMPLOYEE logged in at the till, against the capability the shop
    wired up in the Roles & Permissions catalogue.

    Hiding a button in the browser is therefore a courtesy, never the control.
    These methods refuse an employee without the permission however the call
    arrives.
    """
    _inherit = 'pos.session'

    @api.model
    def _pos_retail_check_till_permission(self, employee_id, capability, action_label):
        """Return the employee if they hold the capability, or refuse loudly."""
        employee = self.env['hr.employee'].sudo().browse(int(employee_id)).exists()
        if not employee:
            raise UserError(_("No cashier is logged in at this till."))
        groups = self.env['pos.retail.access.permission'] \
            ._pos_retail_till_capability_groups().get(capability) or []
        user = employee.user_id
        if not user or not set(user.all_group_ids.ids).intersection(groups):
            raise UserError(_(
                "%(name)s is not allowed to %(action)s.\n\n"
                "This is granted under Staff & Access > Roles & Permissions, "
                "and it applies to the cashier's own login rather than to this "
                "till.",
                name=employee.name, action=action_label,
            ))
        return employee

    # ------------------------------------------------------------------
    # Stock correction
    # ------------------------------------------------------------------
    @api.model
    def pos_retail_stock_snapshot(self, config_id, product_id):
        """What the system thinks is on the shelf, before anybody changes it."""
        config = self.env['pos.config'].sudo().browse(int(config_id))
        product = self.env['product.product'].sudo().browse(int(product_id))
        location = config.picking_type_id.default_location_src_id
        if not location:
            raise UserError(_(
                "This register has no stock location set, so there is nothing "
                "to count against. Set an Operation Type on the register."))
        quants = self.env['stock.quant'].sudo()._gather(product, location)
        return {
            'product_name': product.display_name,
            'location_name': location.display_name,
            'on_hand': sum(quants.mapped('quantity')),
            'uom': product.uom_id.name,
        }

    @api.model
    def pos_retail_adjust_stock(self, config_id, product_id, counted, employee_id, note=False):
        """Correct the shelf quantity of one product, from the till.

        A wrong figure stops a sale with the customer standing there, which is
        why this exists at the counter at all.

        Recorded as a real inventory adjustment, not a silent write: it moves
        stock, and stock that moves without a trace is how a shop stops
        trusting its own numbers. The cashier's name goes on it, so a
        correction can always be traced back to whoever made it.
        """
        employee = self._pos_retail_check_till_permission(
            employee_id, '_can_stock_adjust', _("correct stock"))

        config = self.env['pos.config'].sudo().browse(int(config_id))
        product = self.env['product.product'].sudo().browse(int(product_id))
        location = config.picking_type_id.default_location_src_id
        if not location:
            raise UserError(_("This register has no stock location set."))
        if product.type != 'consu' or not product.is_storable:
            raise UserError(_(
                "%(name)s is not a stocked product, so it has no quantity to "
                "correct.", name=product.display_name))

        Quant = self.env['stock.quant'].sudo().with_company(config.company_id)
        quant = Quant._gather(product, location)[:1]
        if not quant:
            quant = Quant.create({
                'product_id': product.id,
                'location_id': location.id,
                'inventory_quantity': float(counted),
            })
        else:
            quant.inventory_quantity = float(counted)
        quant.inventory_quantity_set = True
        # Named on the adjustment itself. "Counted at the till by Ali" is what
        # makes a difference answerable a week later; an anonymous correction
        # is not.
        quant.inventory_diff_quantity  # force the compute before applying
        quant.with_context(inventory_name=_(
            "Counted at the till by %(name)s%(note)s",
            name=employee.name,
            note=" (%s)" % note if note else "",
        )).action_apply_inventory()

        fresh = Quant._gather(product, location)
        return {
            'product_name': product.display_name,
            'on_hand': sum(fresh.mapped('quantity')),
            'uom': product.uom_id.name,
        }

    # ------------------------------------------------------------------
    # Today's takings
    # ------------------------------------------------------------------
    @api.model
    def pos_retail_daily_sales(self, config_id, employee_id):
        """Today's trading on THIS register, for the person standing at it.

        Scoped to the one register and the one day on purpose. A cashier
        asking "how have we done today" is asking about their counter, and
        widening it to the whole company would turn a routine question into a
        report on every branch's takings.
        """
        self._pos_retail_check_till_permission(
            employee_id, '_can_daily_sales', _("see the day's sales"))

        config = self.env['pos.config'].sudo().browse(int(config_id))
        today = fields.Date.context_today(self)
        orders = self.env['pos.order'].sudo().search([
            ('config_id', '=', config.id),
            ('date_order', '>=', fields.Datetime.to_string(
                fields.Datetime.from_string("%s 00:00:00" % today))),
            ('state', 'in', ('paid', 'done', 'invoiced')),
        ])
        refunds = orders.filtered(lambda o: o.amount_total < 0)
        sales = orders - refunds

        by_method = {}
        for payment in orders.mapped('payment_ids'):
            name = payment.payment_method_id.name or _("Other")
            by_method[name] = by_method.get(name, 0.0) + payment.amount

        return {
            'register': config.name,
            'date': fields.Date.to_string(today),
            'order_count': len(sales),
            'refund_count': len(refunds),
            'sales_total': sum(sales.mapped('amount_total')),
            'refund_total': sum(refunds.mapped('amount_total')),
            'net_total': sum(orders.mapped('amount_total')),
            'by_method': sorted(by_method.items(), key=lambda item: -item[1]),
        }
