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

    # Company-level, not per-till: a barcode identifies the goods, not the
    # counter they were rung up on. Two tills minting codes from different
    # rules would put two stickers on the same pipe.
    pos_retail_auto_product_barcode = fields.Boolean(
        string="Generate Barcodes for New Products", default=True,
        help="Give every new product a scannable barcode automatically when "
             "none was typed or scanned in. Most hardware and sanitary goods "
             "arrive with nothing printed on them, so without this you would "
             "have to invent a number for each one by hand before you could "
             "print a shelf label.\n\n"
             "A barcode you scanned or typed yourself is never replaced. Turn "
             "this off if you only sell branded goods that already carry a "
             "manufacturer's barcode.",
    )
