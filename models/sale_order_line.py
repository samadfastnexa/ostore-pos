from odoo import models


class SaleOrderLine(models.Model):
    _inherit = 'sale.order.line'

    # A quotation line reads as the product's name alone. By default Odoo
    # builds the line description from the product label, which carries the
    # internal reference in brackets ("[MBAHRIA0001] PUTTY"): the shop's own
    # shelf code, meaningless to the customer, and printed on every line of
    # the PDF, the portal page behind the quotation's QR code, and the invoice
    # that copies the description later.
    def _get_sale_order_line_multiline_description_sale(self):
        return super(
            SaleOrderLine, self.with_context(display_default_code=False),
        )._get_sale_order_line_multiline_description_sale()

    # The order-line widget hides the description when it merely repeats this
    # name (sale_product_field.js, get label). It has to lose the code the same
    # way, or every line would show the name a second time underneath itself.
    def _compute_translated_product_name(self):
        return super(
            SaleOrderLine, self.with_context(display_default_code=False),
        )._compute_translated_product_name()
