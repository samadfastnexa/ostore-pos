from odoo import api, fields, models


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

    @api.model
    def _load_pos_data_fields(self, config):
        result = super()._load_pos_data_fields(config)
        for field in ('discount_manager_id', 'discount_reason_id', 'discount_reason_notes', 'discount_input_type'):
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
