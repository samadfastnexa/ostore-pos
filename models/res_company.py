from odoo import fields, models


class ResCompany(models.Model):
    _inherit = 'res.company'

    # Quotation PDF options. Company-level rather than per-till: a quotation
    # is a document the business issues, and it should look the same whichever
    # terminal produced it.
    pos_retail_quote_show_images = fields.Boolean(
        string="Show Product Images on Quotations", default=False,
        help="Print a thumbnail beside each product. Useful when customers "
             "recognise goods by sight; it makes the PDF slower to render and "
             "heavier to email, which is why it is off by default.",
    )
    pos_retail_quote_show_qr = fields.Boolean(
        string="Show QR Code on Quotations", default=True,
        help="Print a QR code the customer can scan to open the quotation "
             "online, review it and accept it.",
    )
