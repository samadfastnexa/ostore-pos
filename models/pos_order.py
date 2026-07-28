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
    # Credit-limit override: who let this customer go further into debt than
    # their limit allowed, and by how much. Recorded so the decision has a name
    # against it, the same way discount approvals do.
    pos_retail_credit_manager_id = fields.Many2one(
        'hr.employee', string="Credit Approved By",
        help="Set when a sale on Customer Account would have taken the customer "
             "past their credit limit and a manager approved it by PIN.",
    )
    pos_retail_credit_over_amount = fields.Monetary(
        string="Amount Over Credit Limit", currency_field='currency_id',
    )

    return_reason_id = fields.Many2one('pos.retail.return.reason', string="Return Reason")
    return_reason_notes = fields.Text(string="Return Reason Notes")

    # --- Receipt management -------------------------------------------------

    def _pos_retail_receipt_data(self):
        """Everything the PDF receipt templates need, computed once here so the
        QWeb stays declarative.

        Order-level discounts are ordinary order lines carrying the config's
        discount product (that is how pos_discount records them), so they are
        separated out of the product lines rather than being a field on the
        order. Round-off comes from this addon's own discount log, which
        already snapshots it at sale time.
        """
        self.ensure_one()
        discount_product = self.config_id.discount_product_id
        order_discount_lines = self.lines.filtered(
            lambda l: discount_product and l.product_id == discount_product)
        product_lines = self.lines - order_discount_lines

        product_discount = sum(
            (l.qty * l.price_unit) * (l.discount or 0.0) / 100.0 for l in product_lines)
        order_discount = abs(sum(order_discount_lines.mapped('price_subtotal_incl')))

        log = self.env['pos.retail.discount.log'].sudo().search(
            [('order_id', '=', self.id)], limit=1)

        # Tax lines grouped by the tax names applied, so a receipt can show
        # "GST 17%: 340.00" rather than one opaque total.
        tax_groups = {}
        for line in product_lines:
            if not line.tax_ids:
                continue
            key = ", ".join(line.tax_ids.mapped('name'))
            tax_groups.setdefault(key, 0.0)
            tax_groups[key] += line.price_subtotal_incl - line.price_subtotal
        if not tax_groups and self.amount_tax:
            tax_groups[_("Tax")] = self.amount_tax

        payments = []
        for payment in self.payment_ids.filtered(lambda p: not p.is_change):
            payments.append({
                'name': payment.payment_method_id.name,
                'amount': payment.amount,
                'date': payment.payment_date,
                'ref': payment.transaction_id or payment.payment_ref_no or (
                    "****%s" % payment.card_no if payment.card_no else ''),
            })

        return {
            'product_lines': product_lines,
            'subtotal': sum(product_lines.mapped('price_subtotal_incl')) + product_discount,
            'product_discount': product_discount,
            'order_discount': order_discount,
            'round_off': log.round_off_amount if log else 0.0,
            'tax_groups': tax_groups,
            'payments': payments,
            'grand_total': self.amount_total,
            'paid': self.amount_paid,
            'change': self.amount_return,
        }

    def action_print_receipt_thermal(self):
        return self.env.ref(
            'pos_retail.action_report_pos_receipt_thermal').report_action(self, config=False)

    def action_print_receipt_a4(self):
        return self.env.ref(
            'pos_retail.action_report_pos_receipt_a4').report_action(self, config=False)

    def action_email_receipt_pdf(self):
        """Open the mail composer pre-loaded with the receipt template; the A4
        PDF rides along as an attachment (mail.template.report_template_ids).
        """
        self.ensure_one()
        template = self.env.ref('pos_retail.mail_template_pos_receipt_pdf', raise_if_not_found=False)
        return {
            'type': 'ir.actions.act_window',
            'name': _("Email Receipt"),
            'res_model': 'mail.compose.message',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_model': 'pos.order',
                'default_res_ids': self.ids,
                'default_template_id': template.id if template else False,
                'default_composition_mode': 'comment',
                'default_partner_ids': self.partner_id.ids,
            },
        }

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
                      'return_reason_id', 'return_reason_notes',
                      'pos_retail_credit_manager_id', 'pos_retail_credit_over_amount'):
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

    # Which package was sold, when the line came from scanning a package
    # barcode. The quantity on the line stays in the product's own unit (so
    # stock moves correctly), and this records the size the customer actually
    # bought, for the receipt and for the package reports.
    pos_retail_package_id = fields.Many2one(
        'product.uom', string="Package", ondelete='set null', index='btree_not_null',
    )

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
                      'pos_retail_price_reason_id', 'pos_retail_package_id'):
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
