from odoo import _, api, fields, models
from odoo.exceptions import UserError


class StockPicking(models.Model):
    """Receiving goods, as a shop assistant experiences it.

    Native receiving is correct but asks warehouse questions: reserve, check
    availability, source and destination locations, packages, owners. A shop
    unpacking a vendor delivery is answering exactly one question per line,
    which is "how many actually turned up?", and then whether to accept a
    short delivery.

    Everything here is a shortcut over the native flow; the underlying moves,
    valuation and backorder handling stay Odoo's.
    """
    _inherit = 'stock.picking'

    pos_retail_expected_qty = fields.Float(
        string="Total Expected", compute='_compute_pos_retail_reception_totals',
        digits='Product Unit of Measure',
        help="Everything the vendor was supposed to send, added up across the "
             "lines below.",
    )
    pos_retail_received_qty = fields.Float(
        string="Total Received", compute='_compute_pos_retail_reception_totals',
        digits='Product Unit of Measure',
        help="What you have entered as actually arrived, added up across the "
             "lines below.",
    )
    pos_retail_reception_state = fields.Selection(
        [
            ('none', "Not checked yet"),
            ('short', "Short delivery"),
            ('exact', "Matches the order"),
            ('over', "More than ordered"),
        ],
        string="Delivery Check", compute='_compute_pos_retail_reception_totals',
        help="Compares what you entered against what was ordered, so a short "
             "or over delivery is obvious before you confirm it. Stays on "
             "\"Not checked yet\" until somebody actually confirms the "
             "quantities, because Odoo fills them in from the order in advance.",
    )

    @api.depends('move_ids.product_uom_qty', 'move_ids.quantity', 'move_ids.picked')
    def _compute_pos_retail_reception_totals(self):
        for picking in self:
            moves = picking.move_ids
            expected = sum(moves.mapped('product_uom_qty'))
            received = sum(moves.mapped('quantity'))
            picking.pos_retail_expected_qty = expected
            picking.pos_retail_received_qty = received

            # Odoo pre-fills the arrived quantity from the order the moment a
            # purchase is confirmed, so a full box on screen proves nothing
            # about a box on the floor. Treat the delivery as checked only
            # once a line is marked picked or somebody has typed a quantity
            # that differs from the order; otherwise this badge would claim a
            # delivery matched before anyone had looked at it.
            rounding = min(moves.mapped('product_id.uom_id.rounding') or [0.01])
            # A typed quantity counts as evidence somebody looked, but an
            # empty one does not: clearing the lines is how you START a count,
            # so it must read as "not checked" rather than as a delivery where
            # nothing turned up.
            edited = any(
                m.quantity and abs(m.quantity - m.product_uom_qty) >= rounding
                for m in moves)
            checked = any(moves.mapped('picked')) or edited

            diff = received - expected
            if not checked:
                picking.pos_retail_reception_state = 'none'
            elif abs(diff) < rounding:
                picking.pos_retail_reception_state = 'exact'
            elif diff < 0:
                picking.pos_retail_reception_state = 'short'
            else:
                picking.pos_retail_reception_state = 'over'

    def action_pos_retail_receive_all(self):
        """Accept the delivery exactly as ordered.

        The common case by a wide margin: the vendor sent what was on the
        order. Filling every line by hand to say so is the single biggest
        waste of time in receiving, so this fills them in one press and leaves
        the person to correct only the lines that differ.
        """
        for picking in self:
            if picking.state in ('done', 'cancel'):
                raise UserError(_(
                    "%(name)s is already %(state)s, so its quantities can no "
                    "longer be changed.",
                    name=picking.name, state=picking.state,
                ))
            for move in picking.move_ids:
                move.quantity = move.product_uom_qty
                move.picked = True
        return True

    def action_pos_retail_receive_nothing(self):
        """Clear every line, for a delivery that has not arrived or is being
        counted from scratch."""
        for picking in self:
            if picking.state in ('done', 'cancel'):
                raise UserError(_(
                    "%(name)s is already %(state)s, so its quantities can no "
                    "longer be changed.", name=picking.name, state=picking.state,
                ))
            for move in picking.move_ids:
                move.quantity = 0.0
                move.picked = False
        return True
