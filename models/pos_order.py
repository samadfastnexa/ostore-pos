from odoo import _, api, fields, models
from odoo.exceptions import ValidationError
from odoo.tools import float_compare


class PosOrder(models.Model):
    _inherit = 'pos.order'

    discount_manager_id = fields.Many2one(
        'hr.employee', string="Approving Manager",
        help="Set when an order discount exceeded the cashier's limit and a "
             "manager authenticated via PIN to approve it.",
    )
    discount_reason_id = fields.Many2one('pos.retail.discount.reason', string="Discount Reason")
    discount_reason_notes = fields.Text(string="Discount Reason Notes")
    discount_input_type = fields.Selection(
        [('fixed', 'Fixed Amount'), ('percent', 'Percentage')],
        string="Discount Entry Type",
    )
    return_reason_id = fields.Many2one('pos.retail.return.reason', string="Return Reason")
    return_reason_notes = fields.Text(string="Return Reason Notes")

    @api.model
    def _load_pos_data_fields(self, config):
        result = super()._load_pos_data_fields(config)
        # An empty list means "load every field" (pos.load.mixin default, which
        # core pos.order relies on) — appending names to it would narrow the
        # schema to only those fields and break the whole POS (no lines, no
        # totals). Only append when a base module has set an explicit list.
        if not result:
            return result
        for field in ('discount_manager_id', 'discount_reason_id', 'discount_reason_notes', 'discount_input_type',
                      'return_reason_id', 'return_reason_notes'):
            if field not in result:
                result.append(field)
        return result

    def _process_saved_order(self, draft):
        # Snapshot stock BEFORE calling super() (which is where the picking
        # actually gets created+validated, decrementing stock) so we capture
        # a genuine "before" reading, then let the arithmetic (previous - qty)
        # derive "after" rather than re-reading live (which could pick up
        # other concurrent orders' effects under multi-terminal load).
        movement_lines = self.env['pos.order.line']
        stock_before = {}
        will_create_picking = (
            not draft and self.state != 'cancel'
            and not self.picking_ids and not self.shipping_date
            and self._should_create_picking_real_time()
        )
        if will_create_picking:
            movement_lines = self.lines.filtered(
                lambda l: l.product_id.type == 'consu' and l.product_id.is_storable and l.qty
            )
            for product in movement_lines.product_id:
                stock_before[product.id] = product.qty_available

        result = super()._process_saved_order(draft)

        if movement_lines:
            self.env['pos.retail.inventory.movement'].sudo()._create_from_order_lines(
                movement_lines, stock_before
            )

        if not draft and self.state != 'cancel':
            self.env['pos.retail.discount.log'].sudo()._create_from_order(self)

        return result


class PosOrderLine(models.Model):
    _inherit = 'pos.order.line'

    # Snapshots of the product's selling range as it stood when the sale was
    # rung up. The product's own prices drift over time, so reporting "sold
    # below default" months later has to compare against what was in force then.
    pos_retail_default_price = fields.Monetary(
        string="Default Price", currency_field='currency_id',
        help="The product's standard selling price at the moment of sale.",
    )
    pos_retail_min_price = fields.Monetary(
        string="Minimum Allowed Price", currency_field='currency_id',
    )
    pos_retail_max_price = fields.Monetary(
        string="Maximum Allowed Price", currency_field='currency_id',
    )
    pos_retail_price_state = fields.Selection(
        [
            ('default', "Default Price"),
            ('adjusted', "Adjusted (within range)"),
            ('overridden', "Overridden (outside range)"),
        ],
        string="Price Status", default='default', index=True,
    )
    pos_retail_price_manager_id = fields.Many2one(
        'hr.employee', string="Price Approved By",
        help="Set when the price fell outside the allowed range and a manager "
             "authenticated via PIN to approve it.",
    )
    pos_retail_price_reason_id = fields.Many2one(
        'pos.retail.price.reason', string="Price Reason",
    )
    pos_retail_price_variance = fields.Monetary(
        string="Price Variance", currency_field='currency_id',
        compute='_compute_pos_retail_price_variance', store=True,
        help="Difference between the price actually charged and the product's "
             "default selling price at the time of sale. Negative means sold "
             "below the default.",
    )

    @api.depends('price_unit', 'pos_retail_default_price')
    def _compute_pos_retail_price_variance(self):
        # Stored so the report can filter on it: an Odoo domain cannot compare
        # two fields to each other, so "sold below default" needs a real column.
        for line in self:
            if line.pos_retail_default_price:
                line.pos_retail_price_variance = line.price_unit - line.pos_retail_default_price
            else:
                line.pos_retail_price_variance = 0.0

    @api.model
    def _load_pos_data_fields(self, config):
        result = super()._load_pos_data_fields(config)
        # Same guard as pos.order above: an empty list means "load every field",
        # so appending to it would narrow the schema and break the POS.
        if not result:
            return result
        for field in ('pos_retail_default_price', 'pos_retail_min_price', 'pos_retail_max_price',
                      'pos_retail_price_state', 'pos_retail_price_manager_id',
                      'pos_retail_price_reason_id'):
            if field not in result:
                result.append(field)
        return result

    def _pos_retail_price_check_applies(self):
        """Only ordinary positive-quantity sale lines are range-checked.

        Refund lines carry a negative quantity and are priced from the original
        order, the order-level discount line is a synthetic negative line on the
        config's discount product, and free lines have nothing to validate.
        """
        self.ensure_one()
        if self.qty <= 0 or self.price_unit <= 0:
            return False
        discount_product = self.order_id.config_id.discount_product_id
        if discount_product and self.product_id.id == discount_product.id:
            return False
        return True

    @api.constrains('price_unit', 'pos_retail_min_price', 'pos_retail_max_price',
                    'pos_retail_price_manager_id')
    def _check_price_within_allowed_range(self):
        """Enforce the selling range server-side.

        The POS gate for price control (cashierHasPriceControlRights) is UI-only
        -- nothing in core validates the posted price -- so a tampered client
        could push any amount. A price outside the range is only accepted when a
        manager actually approved it.
        """
        precision = self.env['decimal.precision'].precision_get('Product Price')
        for line in self:
            if line.pos_retail_price_manager_id or not line._pos_retail_price_check_applies():
                continue
            minimum = line.pos_retail_min_price
            maximum = line.pos_retail_max_price
            if minimum and float_compare(line.price_unit, minimum, precision_digits=precision) < 0:
                raise ValidationError(_(
                    "The price %(price).2f for \"%(product)s\" is below the minimum "
                    "selling price of %(minimum).2f. A manager must approve it.",
                    price=line.price_unit, product=line.product_id.display_name,
                    minimum=minimum,
                ))
            if maximum and float_compare(line.price_unit, maximum, precision_digits=precision) > 0:
                raise ValidationError(_(
                    "The price %(price).2f for \"%(product)s\" exceeds the maximum "
                    "selling price of %(maximum).2f. A manager must approve it.",
                    price=line.price_unit, product=line.product_id.display_name,
                    maximum=maximum,
                ))
