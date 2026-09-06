"""Keep the holding company out of "which branch?" pickers on core models.

Every field here asks which shop a record belongs to, and every one of them
offered MURSHID Company -- a company with no till, no shelves, no customers and
no stock. Choosing it files the record somewhere it can never be acted on, and
in a branch-isolated database that usually means it disappears from both shops
without a word.

Two things are needed per field, not one.

The `domain` decides what the dropdown offers. On its own it is not enough for
a field that also defaults to `self.env.company`: create the record while the
owner happens to be switched into the holding company and the field is stamped
with a value that is missing from its own list -- a required box holding
something it will not let you re-pick. So the default is redirected too,
wherever core sets one.

Neither is a server-side constraint. A many2one domain filters an autocomplete;
it never invalidates a stored value, so every existing record keeps opening,
editing and saving exactly as before and nothing needs migrating.

Deliberately NOT here: journals, accounts, taxes and fiscal positions. Those
genuinely belong to the legal entity, and branches already reach them through
core's parent_of rules without holding the parent themselves.
"""

from odoo import fields, models

from .res_company import TRADING_COMPANY_DOMAIN, pos_retail_trading_company


class SaleOrder(models.Model):
    _inherit = 'sale.order'

    # Quotations raised from the till. Required, and core defaults it to the
    # active company.
    company_id = fields.Many2one(
        domain=TRADING_COMPANY_DOMAIN,
        default=lambda self: pos_retail_trading_company(self.env))


class PurchaseOrder(models.Model):
    _inherit = 'purchase.order'

    # A purchase order is a shop restocking its own shelves. Also exposed as an
    # inline-editable column on the Purchase Orders list, which a view-level
    # domain would have missed -- hence the field override rather than a view
    # patch.
    company_id = fields.Many2one(
        domain=TRADING_COMPANY_DOMAIN,
        default=lambda self: pos_retail_trading_company(self.env))


class StockScrap(models.Model):
    _inherit = 'stock.scrap'

    # Recording damage. The write-off comes out of a shop's stock, and the
    # scrap location is derived from this company's warehouse, so the holding
    # company has nowhere to move the goods from or to.
    company_id = fields.Many2one(
        domain=TRADING_COMPANY_DOMAIN,
        default=lambda self: pos_retail_trading_company(self.env))


class ProductPricelist(models.Model):
    _inherit = 'product.pricelist'

    # pos_retail's own branch rule drops core's parent_of inheritance for
    # pricelists, so a branch does NOT get to use its parent's. A pricelist
    # stamped with the holding company is readable by nobody who sells: it
    # cannot be attached to a register and can never price a line. Blank still
    # means "every branch" and remains the more useful answer.
    company_id = fields.Many2one(
        domain=TRADING_COMPANY_DOMAIN,
        default=lambda self: pos_retail_trading_company(self.env))


class ProductSupplierInfo(models.Model):
    _inherit = 'product.supplierinfo'

    # Vendor pricelists. Blank is honoured as "every branch" by
    # _get_filtered_supplier, so the parent is already served without needing
    # to be pickable.
    company_id = fields.Many2one(
        domain=TRADING_COMPANY_DOMAIN,
        default=lambda self: pos_retail_trading_company(self.env))


class ProductTemplate(models.Model):
    _inherit = 'product.template'

    # Optional, and core ships no default: blank means "visible to all", which
    # is the sensible answer for a catalogue line. Only the dropdown needed
    # narrowing. This is the ownership field, separate from the
    # pos_retail_branch_ids "Sell in Branches" list.
    company_id = fields.Many2one(domain=TRADING_COMPANY_DOMAIN)


class ResPartner(models.Model):
    _inherit = 'res.partner'

    # Customers and vendors. Optional and undefaulted in core; a blank company
    # is a contact both shops can trade with, which is what shared vendors
    # rely on.
    company_id = fields.Many2one(domain=TRADING_COMPANY_DOMAIN)
