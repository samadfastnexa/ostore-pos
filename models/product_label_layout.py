from odoo import _, api, fields, models
from odoo.exceptions import UserError


class ProductLabelLayout(models.TransientModel):
    """Let a shop print price labels with no barcode on them.

    Two reasons, and the second is the urgent one.

    Loose hardware -- washers, elbows, lengths cut off a coil -- often carries
    no barcode worth scanning, and a label with an unscannable code printed on
    it just wastes the space a price could have used.

    And barcode images are the one part of a label that needs a working
    graphics stack. reportlab renders them through rlPyCairo or a compiled
    _rl_renderPM, and where neither is installed EVERY label format fails with
    a RenderPMError and the shop cannot print anything at all. That is exactly
    what happened on the live server. Turning the barcode off prints labels
    today, on the same machine, without waiting for a Python package to be
    installed on a trading system.
    """
    _inherit = 'product.label.layout'

    pos_retail_print_barcode = fields.Boolean(
        string="Print Barcode", default=True,
        help="Untick to print the name and price only. Useful for items with "
             "no barcode worth scanning, and the way to keep printing labels "
             "if barcode images are failing on the server.",
    )
    pos_retail_print_price = fields.Boolean(
        string="Print Price", default=True,
        help="Untick to print a barcode and name with no price on it: for "
             "shelf edges and bin labels that outlive a price change, or "
             "stock going out to someone who should not see retail.\n\n"
             "Core only offers a no-price layout at 4 x 12; this works at "
             "every size.",
    )

    # Format now names a SIZE and nothing else. Leaving "with price" on the
    # labels while a Print Price switch sits above them meant the screen
    # contradicted itself: pick "2 x 7 with price", turn the switch off, and
    # the format still claimed a price it would not print.
    #
    # The plain "4 x 12" entry is gone for the same reason. Its template is
    # the same 43mm x 19mm label as the priced one -- the ONLY difference was
    # the price, which is now the switch's job, so it was the same choice
    # offered twice.
    #
    # The two ZPL entries stay as they are: ZPL is generated as printer
    # commands by stock, not through these QWeb templates, so neither switch
    # reaches it and its own with/without price choice is still the real one.
    print_format = fields.Selection(
        selection=[
            ('dymo', "Dymo"),
            ('2x7xprice', "2 x 7"),
            ('4x7xprice', "4 x 7"),
            ('4x12xprice', "4 x 12"),
            ('zpl', "ZPL Labels"),
            ('zplxprice', "ZPL Labels with price"),
        ],
        ondelete={'zpl': 'set default', 'zplxprice': 'set default'},
    )

    def action_pos_retail_preview(self):
        """Show the sheet on screen before anything is printed.

        Same report, same data, rendered as HTML instead of PDF, so it opens
        in a tab in about the time a click takes rather than going through
        wkhtmltopdf and landing in the downloads folder. Odoo already does
        this for ZPL, which carries a zpl_preview image on this very wizard;
        the paper formats simply never got the equivalent.

        Worth one caution, stated on the button's own help: a browser lays
        HTML out slightly differently from the PDF engine, so this is a
        faithful check of CONTENT -- is the price there, is the barcode gone,
        is the name complete -- and only a close guide to millimetre spacing.
        Print one sheet before committing a roll.
        """
        self.ensure_one()
        xml_id, data = self._prepare_report_data()
        if not xml_id:
            raise UserError(_("Unable to find report template for %s format", self.print_format))
        if 'zpl' in self.print_format:
            raise UserError(_(
                "ZPL labels are printer commands rather than a page, so there "
                "is nothing to show here. The ZPL Template field above has its "
                "own preview image."))
        report = self.env.ref(xml_id)
        action = report.report_action(None, data=data, config=False)
        # qweb-html sends the web client to /report/html/... instead of
        # /report/pdf/..., and keeping the dialog open means the format and
        # the two switches can be changed and previewed again immediately.
        action['report_type'] = 'qweb-html'
        action['close_on_report_download'] = False
        return action

    def _prepare_report_data(self):
        """Carry the choice into the report's own data.

        The templates cannot read the wizard's fields, only what
        product_label_report.py puts in the values dict, and that passes
        `data` straight through. Adding the flag here is what lets the
        inherited templates hide the barcode.
        """
        xml_id, data = super()._prepare_report_data()
        data['pos_retail_print_barcode'] = self.pos_retail_print_barcode
        data['pos_retail_print_price'] = self.pos_retail_print_price
        return xml_id, data


class ReportProductLabel(models.AbstractModel):
    """Expose the flag to every label template.

    _get_report_values in product_label_report.py builds a fixed dict and does
    not pass `data` on, so a template has no way to see the new key without
    this. Applied to the label report models rather than to the module-level
    helper they all call, because that helper is a plain function.
    """
    _inherit = 'report.product.report_producttemplatelabel2x7'

    @api.model
    def _get_report_values(self, docids, data=None):
        values = super()._get_report_values(docids, data=data)
        values['pos_retail_print_barcode'] = (data or {}).get(
            'pos_retail_print_barcode', True)
        values['pos_retail_print_price'] = (data or {}).get(
            'pos_retail_print_price', True)
        return values


class ReportProductLabel4x7(models.AbstractModel):
    _inherit = 'report.product.report_producttemplatelabel4x7'

    @api.model
    def _get_report_values(self, docids, data=None):
        values = super()._get_report_values(docids, data=data)
        values['pos_retail_print_barcode'] = (data or {}).get(
            'pos_retail_print_barcode', True)
        values['pos_retail_print_price'] = (data or {}).get(
            'pos_retail_print_price', True)
        return values


class ReportProductLabel4x12(models.AbstractModel):
    _inherit = 'report.product.report_producttemplatelabel4x12'

    @api.model
    def _get_report_values(self, docids, data=None):
        values = super()._get_report_values(docids, data=data)
        values['pos_retail_print_barcode'] = (data or {}).get(
            'pos_retail_print_barcode', True)
        values['pos_retail_print_price'] = (data or {}).get(
            'pos_retail_print_price', True)
        return values


class ReportProductLabel4x12Noprice(models.AbstractModel):
    _inherit = 'report.product.report_producttemplatelabel4x12noprice'

    @api.model
    def _get_report_values(self, docids, data=None):
        values = super()._get_report_values(docids, data=data)
        values['pos_retail_print_barcode'] = (data or {}).get(
            'pos_retail_print_barcode', True)
        values['pos_retail_print_price'] = (data or {}).get(
            'pos_retail_print_price', True)
        return values


class ReportProductLabelDymo(models.AbstractModel):
    _inherit = 'report.product.report_producttemplatelabel_dymo'

    @api.model
    def _get_report_values(self, docids, data=None):
        values = super()._get_report_values(docids, data=data)
        values['pos_retail_print_barcode'] = (data or {}).get(
            'pos_retail_print_barcode', True)
        values['pos_retail_print_price'] = (data or {}).get(
            'pos_retail_print_price', True)
        return values
