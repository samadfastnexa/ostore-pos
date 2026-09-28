from odoo import fields, models

# A Barcode column for every back-office screen that lists products.
#
# Odoo shows a product as "[MBAHRIA0001] PUTTY", with the code folded into the
# name where it can be neither read at a glance nor sorted apart. Those screens
# now show the name alone (the pos_retail_hide_product_code switch on
# product.product) and the code here, in a column of its own.
#
# All read-only and unstored: nothing is duplicated in the database, and a
# readonly related field is never sent back on save -- which matters for
# stock.quant, whose inventory mode refuses any write outside its own short
# list of fields. Unstored related fields also work on the SQL-view reports
# below (_auto = False), which have no column to hold one.


def _barcode_field():
    return fields.Char(related='product_id.barcode', string="Barcode")


class StockQuant(models.Model):
    _inherit = 'stock.quant'

    pos_retail_product_barcode = _barcode_field()


class StockScrap(models.Model):
    _inherit = 'stock.scrap'

    pos_retail_product_barcode = _barcode_field()


class StockMove(models.Model):
    _inherit = 'stock.move'

    pos_retail_product_barcode = _barcode_field()


class PosOrderLine(models.Model):
    _inherit = 'pos.order.line'

    pos_retail_product_barcode = _barcode_field()


class PosRetailLineDiscountLog(models.Model):
    _inherit = 'pos.retail.line.discount.log'

    pos_retail_product_barcode = _barcode_field()


class PosRetailCustomerRefundItem(models.Model):
    _inherit = 'pos.retail.customer.refund.item'

    pos_retail_product_barcode = _barcode_field()


class PosRetailVendorReturnItem(models.Model):
    _inherit = 'pos.retail.vendor.return.item'

    pos_retail_product_barcode = _barcode_field()


class PosRetailCustomerRefundLine(models.Model):
    _inherit = 'pos.retail.customer.refund.line'

    pos_retail_product_barcode = _barcode_field()


class PosRetailVendorRefundLine(models.Model):
    _inherit = 'pos.retail.vendor.refund.line'

    pos_retail_product_barcode = _barcode_field()
