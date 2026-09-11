from odoo import fields, models


class PosRetailVendorReturnReason(models.Model):
    """Why goods are being sent back to a supplier.

    Kept apart from the customer return reasons on purpose. A customer
    bringing back a tap they changed their mind about and the shop sending a
    carton of cracked fittings back to the wholesaler are different events
    with different vocabularies, and a single shared list would put "Changed
    mind" in front of the person arranging a supplier return, and "Damaged in
    transit" in front of a cashier at the till.
    """
    _name = 'pos.retail.vendor.return.reason'
    _description = "Vendor Return Reason"
    _order = 'sequence, id'

    name = fields.Char(
        required=True, translate=True,
        help="Why the goods are going back, for example 'Damaged in transit', "
             "'Wrong item supplied' or 'Excess stock'. Saved on the return, so "
             "the Vendor Refunds reports can show what keeps going wrong with "
             "which supplier.",
    )
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)

    _name_uniq = models.Constraint(
        'unique(name)', "A vendor return reason with this name already exists.")
