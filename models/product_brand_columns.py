from odoo import fields, models

# A Brand column for stock screens and back-office screens that list products.
#
# Mirrors product_barcode_columns.py: gives staff an immediate view of the
# brand / maker on stock counts, inventory adjustments, damage logs, goods
# receipts, and stock reports without drilling into individual records.
#
# All read-only and unstored: nothing is duplicated in the database, and a
# readonly related field is never sent back on save -- which matters for
# stock.quant, whose inventory mode refuses any write outside its own short
# list of fields.


def _brand_field():
    return fields.Many2one(
        'product.brand',
        related='product_id.brand_id',
        string="Brand",
        readonly=True,
    )


class StockQuant(models.Model):
    _inherit = 'stock.quant'

    brand_id = _brand_field()
    pos_retail_brand_id = _brand_field()


class StockScrap(models.Model):
    _inherit = 'stock.scrap'

    brand_id = _brand_field()
    pos_retail_brand_id = _brand_field()


class StockMove(models.Model):
    _inherit = 'stock.move'

    brand_id = _brand_field()
    pos_retail_brand_id = _brand_field()


class PosOrderLine(models.Model):
    _inherit = 'pos.order.line'

    brand_id = _brand_field()
    pos_retail_brand_id = _brand_field()


class PosRetailLineDiscountLog(models.Model):
    _inherit = 'pos.retail.line.discount.log'

    brand_id = _brand_field()
    pos_retail_brand_id = _brand_field()


class PosRetailCustomerRefundItem(models.Model):
    _inherit = 'pos.retail.customer.refund.item'

    brand_id = _brand_field()
    pos_retail_brand_id = _brand_field()


class PosRetailVendorReturnItem(models.Model):
    _inherit = 'pos.retail.vendor.return.item'

    brand_id = _brand_field()
    pos_retail_brand_id = _brand_field()


class PosRetailCustomerRefundLine(models.Model):
    _inherit = 'pos.retail.customer.refund.line'

    brand_id = _brand_field()
    pos_retail_brand_id = _brand_field()


class PosRetailVendorRefundLine(models.Model):
    _inherit = 'pos.retail.vendor.refund.line'

    brand_id = _brand_field()
    pos_retail_brand_id = _brand_field()


class PosRetailInventoryMovement(models.Model):
    _inherit = 'pos.retail.inventory.movement'

    brand_id = _brand_field()
    pos_retail_brand_id = _brand_field()
