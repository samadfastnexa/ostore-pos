from datetime import timedelta

from odoo import _, api, fields, models
from odoo.exceptions import ValidationError

from .res_company import TRADING_COMPANY_DOMAIN

# What an offer can be aimed at. Ordered the way a shopkeeper thinks about it,
# widest first, because the field is a radio list and the order is the reading
# order.
SCOPE_SELECTION = [
    ('all', "All products"),
    ('products', "Selected products"),
    ('category', "Product category"),
    ('brand', "Brand"),
    ('brand_products', "Selected products of a brand"),
    ('tags', "Product tags"),
]


class PosRetailBrandCampaign(models.Model):
    """A promotion that runs itself: "Sonex, 10% off, for the next 15 days".

    Separate from the cashier discount on purpose. That one is a decision made
    at the counter, one bill at a time, by a person. This one is an
    arrangement made in advance: it applies by itself to every matching item,
    on every till, until the moment it ends, and nobody has to remember it.

    The two still print as a SINGLE discount on the bill, because a customer
    does not care which part of the money off came from where. That holds for
    a fixed selling price too: the line shows the normal price and the
    difference joins the same discount, so the customer can see what they
    saved rather than just a lower number they cannot check.

    Keeps the technical name pos.retail.brand.campaign, which is now narrower
    than what it does. Renaming a model means moving its table, its access
    rules and every reference to them on a database that is already trading,
    which is a real risk taken for a tidier word; the label everywhere a
    person looks says Promotion.
    """
    _name = 'pos.retail.brand.campaign'
    _description = "POS Promotion"
    _inherit = ['pos.load.mixin']
    _order = 'date_end desc, id desc'

    name = fields.Char(
        string="Promotion Name", required=True,
        help="What to call this offer, for your own records. Something you "
             "will recognise on a report months later, such as "
             "'Sonex winter 10%'.",
    )

    # --- what it takes off ---------------------------------------------------
    discount_type = fields.Selection(
        [('percent', "Percentage (%)"),
         ('amount', "Fixed amount off"),
         ('fixed_price', "Fixed selling price")],
        string="Discount Type", required=True, default='percent',
        help="Percentage: a share off the normal price.\n"
             "Fixed amount off: the same money off EACH ITEM sold, so three "
             "of them take off three times as much.\n"
             "Fixed selling price: the item sells for this price instead, "
             "whatever it normally costs.",
    )
    discount_value = fields.Float(
        string="Value", required=True, default=10.0,
        help="The number that goes with the type above: 10 for ten percent, "
             "50 for fifty rupees off each item, or 250 to sell at 250.",
    )

    # --- what it applies to --------------------------------------------------
    scope = fields.Selection(
        SCOPE_SELECTION, string="Apply To", required=True, default='brand',
        help="Which items this offer covers. Everything below changes to "
             "match what you pick here.",
    )
    brand_id = fields.Many2one(
        'product.brand', string="Brand", ondelete='cascade', index=True,
        help="The maker running the offer.",
    )
    product_ids = fields.Many2many(
        'product.template', string="Products",
        help="The exact items this offer covers.",
    )
    categ_ids = fields.Many2many(
        'product.category', string="Product Categories",
        help="Every product filed under these categories, including their "
             "sub-categories.",
    )
    tag_ids = fields.Many2many(
        'product.tag', string="Product Tags",
        help="Every product carrying any of these tags.",
    )

    # --- when it runs --------------------------------------------------------
    date_start = fields.Datetime(
        string="Starts", required=True, default=fields.Datetime.now,
        help="The moment the offer begins. Nothing is discounted before it.",
    )
    date_end = fields.Datetime(
        string="Ends", required=True,
        help="The moment the offer stops. After it, the tills go back to full "
             "price on their own, with nobody having to switch anything off.\n\n"
             "Set by the Duration buttons, or type an exact date and time here.",
    )
    duration_preset = fields.Selection(
        [('7', "1 Week"), ('15', "15 Days"), ('30', "1 Month"), ('custom', "Custom")],
        string="Duration", default='15', store=False,
        help="How long the offer runs, counted from Starts. Pick one and Ends "
             "is filled in for you -- for anything else, choose Custom and "
             "type the exact end.",
    )

    company_id = fields.Many2one(
        'res.company', string="Branch", domain=TRADING_COMPANY_DOMAIN, index=True,
        help="Leave empty to run the offer at every branch, which is normal "
             "for a maker's own campaign. Name a branch only when one shop is "
             "running it alone.",
    )
    active = fields.Boolean(
        default=True,
        help="Untick to stop an offer immediately, or to keep a finished one "
             "on record without it running.",
    )
    state = fields.Selection(
        [('scheduled', "Not started yet"), ('running', "Running now"),
         ('finished', "Finished")],
        compute='_compute_state', store=False,
        help="Worked out from the clock against the two dates above.",
    )
    product_count = fields.Integer(
        string="# Products", compute='_compute_product_count',
        help="How many items this offer actually covers today.",
    )

    @api.onchange('duration_preset', 'date_start')
    def _onchange_duration_preset(self):
        # A convenience for typing nothing, not a source of truth: this only
        # ever WRITES date_end, and is not itself stored, so it never fights
        # with someone who prefers to type an exact end directly.
        if self.duration_preset and self.duration_preset != 'custom':
            start = self.date_start or fields.Datetime.now()
            self.date_end = start + timedelta(days=int(self.duration_preset))

    @api.depends('date_start', 'date_end', 'active')
    def _compute_state(self):
        now = fields.Datetime.now()
        for promo in self:
            if promo.date_start and promo.date_start > now:
                promo.state = 'scheduled'
            elif promo.date_end and promo.date_end < now:
                promo.state = 'finished'
            else:
                promo.state = 'running'

    @api.depends('scope', 'brand_id', 'product_ids', 'categ_ids', 'tag_ids')
    def _compute_product_count(self):
        for promo in self:
            promo.product_count = len(promo._covered_products())

    def action_view_products(self):
        self.ensure_one()
        products = self._covered_products()
        return {
            'type': 'ir.actions.act_window',
            'name': _("Products in %s", self.name),
            'res_model': 'product.template',
            'view_mode': 'list,form',
            'domain': [('id', 'in', products.ids)],
        }

    def _covered_products(self):
        """Every product this offer applies to, however it was aimed.

        One place, used by BOTH the count shown on the form and the list the
        till is sent, so what the shop is promised and what the register
        actually discounts cannot drift apart.
        """
        self.ensure_one()
        Template = self.env['product.template']
        sellable = [('sale_ok', '=', True)]

        if self.scope == 'all':
            return Template.search(sellable)
        if self.scope == 'products':
            return self.product_ids
        if self.scope == 'category':
            if not self.categ_ids:
                return Template
            # child_of, not "in": filing an offer under Sanitary is meant to
            # cover Sanitary > Fittings too, which is how the categories are
            # arranged in the first place.
            return Template.search(sellable + [('categ_id', 'child_of', self.categ_ids.ids)])
        if self.scope == 'brand':
            if not self.brand_id:
                return Template
            return Template.search(sellable + [('brand_id', '=', self.brand_id.id)])
        if self.scope == 'brand_products':
            return self.product_ids.filtered(
                lambda p: not self.brand_id or p.brand_id == self.brand_id)
        if self.scope == 'tags':
            if not self.tag_ids:
                return Template
            return Template.search(sellable + [('product_tag_ids', 'in', self.tag_ids.ids)])
        return Template

    @api.constrains('discount_type', 'discount_value')
    def _check_discount_value(self):
        for promo in self:
            name = promo.name or _("this offer")
            if promo.discount_value <= 0:
                raise ValidationError(_(
                    "The value on %(name)s is %(value)s. It has to be more "
                    "than nothing for the offer to do anything.",
                    name=name, value=promo.discount_value,
                ))
            if promo.discount_type == 'percent' and promo.discount_value > 100:
                raise ValidationError(_(
                    "The discount on %(name)s is %(value)s%%, which cannot be "
                    "right. Enter a number above 0 and no more than 100 -- "
                    "type 10 for ten percent off, not 0.1.",
                    name=name, value=promo.discount_value,
                ))

    @api.constrains('scope', 'brand_id', 'product_ids', 'categ_ids', 'tag_ids')
    def _check_scope_target(self):
        """An offer aimed at nothing discounts nothing, silently.

        Saving in that state looks like success and is only discovered when a
        customer does not get their money off, so it is refused here instead.
        """
        needed = {
            'products': ('product_ids', _("at least one product")),
            'category': ('categ_ids', _("at least one category")),
            'brand': ('brand_id', _("a brand")),
            'brand_products': ('product_ids', _("at least one product")),
            'tags': ('tag_ids', _("at least one tag")),
        }
        for promo in self:
            target = needed.get(promo.scope)
            if target and not promo[target[0]]:
                raise ValidationError(_(
                    "%(name)s is set to apply to \"%(scope)s\" but names "
                    "%(missing)s, so it would cover nothing at all.",
                    name=promo.name or _("This offer"),
                    scope=dict(SCOPE_SELECTION).get(promo.scope, promo.scope),
                    missing=_("no %s", target[1]),
                ))

    @api.constrains('date_start', 'date_end')
    def _check_dates(self):
        for promo in self:
            if promo.date_start and promo.date_end and promo.date_end < promo.date_start:
                raise ValidationError(_(
                    "%(name)s is set to end on %(end)s, before it starts on "
                    "%(start)s, so it would never run at all.",
                    name=promo.name or _("This offer"),
                    end=promo.date_end, start=promo.date_start,
                ))

    # ------------------------------------------------------------------
    # Point of Sale
    # ------------------------------------------------------------------
    @api.model
    def _load_pos_data_domain(self, data, config):
        """Every promotion for this branch, NOT narrowed to "live now".

        POS only reloads records that changed since the last sync (see
        pos.load.mixin._server_date_to_domain), and a promotion's write_date
        does not move at the moment it starts or ends -- nobody edits the
        record, the clock just passes it. Filtering by date here would mean an
        offer that goes live overnight, or one that quietly expires, never
        reaches a session that was already open: exactly backwards from what a
        time-boxed offer needs.

        Loyalty programs solve the same problem the same way (see
        pos_loyalty/models/loyalty_program.py): ship every record for the
        config and let the browser compare the clock against date_start /
        date_end at the moment a discount is actually computed.
        """
        return [
            '|', ('company_id', '=', False),
                 ('company_id', '=', config.company_id.id),
        ]

    @api.model
    def _load_pos_data_fields(self, config):
        return ['id', 'name', 'discount_type', 'discount_value',
                'date_start', 'date_end']

    @api.model
    def _load_pos_data_read(self, records, config):
        """Ship the product ids each offer covers, resolved on the server.

        The till cannot work them out for itself: scope can mean a category
        tree, a tag or a whole brand, and none of brand_id, categ_id's
        ancestry or product_tag_ids is part of the POS payload in a form the
        browser could search. Expanding here also means the count the shop
        sees on the form is the same list the register discounts.
        """
        read_records = super()._load_pos_data_read(records, config)
        covered = {c.id: c._covered_products().ids for c in records.sudo()}
        for row in read_records:
            row['_product_tmpl_ids'] = covered.get(row['id'], [])
        return read_records
