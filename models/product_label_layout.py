from odoo import _, api, fields, models


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
