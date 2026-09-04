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

        for company in self:
            sales = self.env['pos.order'].sudo().search_count(
                [('company_id', '=', company.id)])
            entries = self.env['account.move'].sudo().search_count(
                [('company_id', '=', company.id), ('state', '!=', 'cancel')])
            if sales or entries:
                raise UserError(_(
                    "%(name)s cannot be deleted, because it has traded: "
                    "%(sales)s till sale(s) and %(entries)s accounting "
                    "entry(ies) are recorded against it. Deleting it would "
                    "erase that history, and those are the records the books "
                    "are built from.\n\n"
                    "Hide it instead. It drops out of the day to day, keeps "
                    "its history, and can be unhidden at any time.",
                    name=company.name, sales=sales, entries=entries,
                ))

        return super().unlink()
