from odoo import api, fields, models

# Documents the shop ISSUES itself, so "now" is the right date to suggest.
# Vendor bills are deliberately absent: a bill's date belongs to the supplier's
# paperwork, and silently stamping today would file it in the wrong tax period
# and compute the wrong due date. Keep entering those from the vendor document.
ISSUED_MOVE_TYPES = ('out_invoice', 'out_refund', 'out_receipt')


class AccountMove(models.Model):
    _inherit = 'account.move'

    @api.model
    def default_get(self, fields_list):
        """Pre-fill Invoice Date with today on the customer invoice form.

        Core leaves the field empty and only stamps it when the move is posted
        (account_move.py `_post`), which is why the form shows a grey "Today"
        placeholder instead of a value. The posted result was already today;
        this just makes it visible and editable while the invoice is a draft.

        Gated on `default_move_type` from the action context rather than on the
        move type alone, so this stays a UI convenience. Invoices built in code
        are untouched: sale.order._prepare_invoice() leaves the date to posting
        time, and POS already sets its own from the order date
        (pos_order.py `_prepare_invoice_vals`) -- neither should silently become
        "whenever the record happened to be created".
        """
        values = super().default_get(fields_list)
        if (
            'invoice_date' in fields_list
            and not values.get('invoice_date')
            and self.env.context.get('default_move_type') in ISSUED_MOVE_TYPES
        ):
            values['invoice_date'] = fields.Date.context_today(self)
        return values
