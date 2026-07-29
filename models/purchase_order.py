from odoo import _, api, models
from odoo.exceptions import UserError


class PurchaseOrder(models.Model):
    _inherit = 'purchase.order'

    @api.constrains('partner_id', 'state')
    def _check_vendor_not_blacklisted(self):
        """Stop orders reaching a blacklisted vendor.

        Checked on confirmation rather than on the draft: a buyer may need to
        open an existing order to read what was on it, and blocking that would
        hide the very history that led to the blacklisting. Drafts are also
        where a vendor gets swapped for a good one.
        """
        for order in self:
            if order.state in ('draft', 'sent', 'cancel'):
                continue
            partner = order.partner_id.commercial_partner_id
            if partner.vendor_status == 'blacklisted':
                raise UserError(_(
                    "%(vendor)s is blacklisted, so this order cannot be "
                    "confirmed. Change the vendor, or lift the blacklist on "
                    "their contact form if you have decided to buy from them "
                    "again.", vendor=partner.display_name,
                ))

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
