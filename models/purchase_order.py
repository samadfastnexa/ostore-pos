from odoo import models


class PurchaseOrder(models.Model):
    _inherit = 'purchase.order'

    def button_approve(self, force=False):
        res = super().button_approve(force=force)
        self._pos_retail_affected_supplierinfo().sudo()._compute_last_purchase()
        return res

    def button_cancel(self):
        affected = self._pos_retail_affected_supplierinfo()
        res = super().button_cancel()
        affected.sudo()._compute_last_purchase()
        return res

    def _pos_retail_affected_supplierinfo(self):
        partners = self.partner_id | self.partner_id.commercial_partner_id
        products = self.order_line.product_id
        if not products:
            return self.env['product.supplierinfo']
        return self.env['product.supplierinfo'].search([
            ('partner_id', 'in', partners.ids),
            '|', ('product_id', 'in', products.ids),
                 ('product_tmpl_id', 'in', products.product_tmpl_id.ids),
        ])
