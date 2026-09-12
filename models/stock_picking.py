from odoo import _, api, fields, models
from odoo.exceptions import UserError


class StockPicking(models.Model):
    _inherit = 'stock.picking'

    # Why these goods are going back to the supplier. Only meaningful on a
    # return to a vendor, which is the only place the form shows it; the
    # Vendor Refunds reports group by it.
    pos_retail_vendor_return_reason_id = fields.Many2one(
        'pos.retail.vendor.return.reason', string="Return Reason",
        help="Why the goods are being sent back to the supplier. It feeds the "
             "Vendor Refunds reports, so a supplier whose deliveries keep "
             "arriving damaged shows up as exactly that.",
    )
    pos_retail_is_vendor_return = fields.Boolean(
        compute='_compute_pos_retail_is_vendor_return',
        help="Technical: whether this transfer sends goods back to a supplier.",
    )

    @api.depends('return_id', 'location_dest_id.usage')
    def _compute_pos_retail_is_vendor_return(self):
        # A return whose goods leave for a supplier location. Matched on the
        # destination rather than the operation type, because a shop can name
        # and configure operation types however it likes, while "the goods end
        # up at a supplier" is what actually makes it a vendor return.
        for picking in self:
            picking.pos_retail_is_vendor_return = bool(
                picking.return_id and picking.location_dest_id.usage == 'supplier')

    def action_print_goods_receipt(self):
        """Goods Receipt Note for incoming stock.

        Native ships a Delivery Slip and a Picking Operations sheet, but
        neither carries purchase costs or the signature block a store needs
        when accepting a vendor delivery, which is what this document adds.
        """
        outgoing = self.filtered(lambda p: p.picking_type_code != 'incoming')
        if outgoing:
            raise UserError(_(
                "A Goods Receipt Note only applies to incoming shipments. "
                "Use the Delivery Slip for %(names)s.",
                names=", ".join(outgoing.mapped('name')),
            ))
        return self.env.ref(
            'pos_retail.action_report_goods_receipt').report_action(self, config=False)

    def action_print_vendor_return(self):
        """Vendor Return Note: what is going back to the supplier, why, and
        what it is worth -- the paper a driver signs on the way out and the
        document behind the credit the Vendor Refunds report expects to see
        arrive. Native ships nothing purpose-built for this leg; the
        Delivery Slip it would otherwise fall back to has no reason, no
        cost column and no reference to the delivery it undoes.
        """
        not_returns = self.filtered(lambda p: not p.pos_retail_is_vendor_return)
        if not_returns:
            raise UserError(_(
                "A Vendor Return Note only applies to stock going back to a "
                "supplier. %(names)s is not a vendor return.",
                names=", ".join(not_returns.mapped('name')),
            ))
        return self.env.ref(
            'pos_retail.action_report_vendor_return').report_action(self, config=False)
