from odoo import _, models
from odoo.exceptions import UserError


class StockPicking(models.Model):
    _inherit = 'stock.picking'

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
