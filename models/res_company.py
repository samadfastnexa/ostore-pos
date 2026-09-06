from odoo import _, fields, models
from odoo.exceptions import UserError

# Companies that actually trade, for any field that asks "which branch?".
#
# The parent company here holds only the legal identity -- the chart of
# accounts, the NTN, the taxes. It has no till, no shelves and no customers of
# its own, so offering it in a branch picker is always wrong: choosing it would
# scope the record to a company that can never sell it. A company with branches
# under it is a holding company by definition, so "has no branches of its own"
# is the test. It also keeps working on a plain single-company database, where
# the one company is both the business and the shop.
TRADING_COMPANY_DOMAIN = [('child_ids', '=', False)]


def pos_retail_trading_company(env, prefer_member_shop=False):
    """The company a new shop-level record should be booked against.

    Required company fields on core models default to `self.env.company`, so a
    record created while the owner happens to be switched into the holding
    company is stamped with it -- and a domain alone does not help there. It
    hides the value from the dropdown while the field still displays it, which
    is a worse state than before: a required field holding something absent
    from its own list. Redirect the default as well as the choices.

    Chosen from env.companies -- the companies actually switched ON -- and NOT
    from env.user.company_ids. Those are different sets, and the difference
    bites: ir.rule evaluates `company_ids` as env.companies
    (addons/base/models/ir_rule.py:49), so naming a company the user merely
    belongs to, rather than one they are working in, produces a record the rule
    then refuses. The save dies telling the owner of the system that he has no
    create rights on his own expenses. Tick MURSHID alone in the switcher and
    every redirected default did exactly that.

    prefer_member_shop is for res.users only. A new person must never START in
    the holding company, but their company_id is also constrained by
    pos_retail_assignable_company_ids, so falling back to the active company
    there would put a value in the field that its own dropdown will not offer.
    Fall back to a shop the creator belongs to instead.
    """
    company = env.company
    if not company.child_ids:
        return company

    # Prefer a shop under the company being stood in, then any other switched-on
    # shop, so the answer is always something the record rules will accept.
    active_shops = env.companies.filtered(lambda c: not c.child_ids)
    picked = active_shops.filtered(lambda c: c.parent_id == company) or active_shops
    if picked:
        return picked[0]

    if prefer_member_shop:
        shops = env.user.company_ids.filtered(lambda c: not c.child_ids)
        if shops:
            return shops[0]

    # Nothing that trades is reachable, so answer with nothing. Returning the
    # holding company here would hand back a value TRADING_COMPANY_DOMAIN
    # excludes -- the field's own dropdown would refuse to offer it. The record
    # rule lets it save, so the AccessError this function was written to stop
    # simply becomes a sale, a purchase or an expense quietly filed against a
    # company with no till, which is worse: nothing fails, and nobody looks.
    # Empty leaves a required field blank, so the person picks a real shop.
    return company.browse()


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

    def unlink(self):
        """Refuse to delete a company the business still stands on.

        Core guards none of this. res.company.unlink() only clears a cache, so
        the parent company and any branch can be deleted outright from the
        Companies list. The one thing in the way is parent_id's
        ondelete='restrict' at the database level, and that surfaces as a raw
        foreign key error nobody can act on.

        Deleting a branch is not like deleting a product. It takes its sales,
        its khata balances, its stock and its till with it, and there is no
        undo. In every one of these cases the thing actually wanted is to hide
        it, so the message says so.
        """
        for company in self:
            if company.child_ids:
                raise UserError(_(
                    "%(name)s has branches under it (%(branches)s), so it "
                    "cannot be deleted. It is the company those branches "
                    "belong to, and removing it would leave them with no "
                    "owner.\n\n"
                    "If the business has closed, hide it instead. Everything "
                    "stays in the system and can be unhidden later.",
                    name=company.name,
                    branches=", ".join(company.child_ids.mapped('name')),
                ))

        remaining = self.sudo().with_context(active_test=False).search_count(
            [('id', 'not in', self.ids)])
        if not remaining:
            raise UserError(_(
                "This is the only company left, so it cannot be deleted. Odoo "
                "has to be able to say who the business is on every sale, "
                "invoice and receipt."))

        # Everything a branch owns, not just its till sales. Counting only
        # pos.order and account.move let a branch holding purchases, khata
        # balances or expenses past this guard and straight into a raw
        # RESTRICT foreign key error naming a constraint nobody can act on.
        holdings = [
            ('pos.order', _("till sale")),
            ('account.move', _("accounting entry")),
            ('sale.order', _("quotation or sales order")),
            ('purchase.order', _("purchase order")),
            ('stock.move', _("stock movement")),
            ('pos.retail.expense', _("recorded expense")),
            ('pos.retail.khata.payment', _("khata payment")),
            ('pos.retail.ledger.adjustment', _("ledger adjustment")),
        ]
        for company in self:
            found = []
            for model_name, label in holdings:
                model = self.env.get(model_name)
                if model is None:
                    continue                       # that app is not installed here
                count = model.sudo().with_context(active_test=False).search_count(
                    [('company_id', '=', company.id)])
                if count:
                    found.append("%s %s(s)" % (count, label))
            if found:
                raise UserError(_(
                    "%(name)s cannot be deleted, because it has traded: "
                    "%(what)s are recorded against it. Deleting it would erase "
                    "that history, and those are the records the books are "
                    "built from.\n\n"
                    "Hide it instead. It drops out of the day to day, keeps "
                    "its history, and can be unhidden at any time.",
                    name=company.name, what=", ".join(found),
                ))

        return super().unlink()
