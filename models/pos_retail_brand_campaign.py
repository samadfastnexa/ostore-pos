from datetime import timedelta

from odoo import _, api, fields, models
from odoo.exceptions import ValidationError

from .res_company import TRADING_COMPANY_DOMAIN


class PosRetailBrandCampaign(models.Model):
    """A supplier's own offer: "Sonex, 10% off, for the next 15 days".

    Separate from the cashier discount on purpose. That one is a decision made
    at the counter, one bill at a time, by a person. This one is an arrangement
    with a maker: it applies by itself to every matching item, on every till,
    until the day it ends, and nobody has to remember it.

    The two still print as a SINGLE discount on the bill, because a customer
    does not care which part of the money off came from where.
    """
    _name = 'pos.retail.brand.campaign'
    _description = "Brand Discount Campaign"
    _inherit = ['pos.load.mixin']
    _order = 'date_end desc, id desc'

    name = fields.Char(
        required=True,
        help="What to call this offer, for your own records. Something you "
             "will recognise on a report months later, such as "
             "'Sonex winter 10%'.",
    )
    brand_id = fields.Many2one(
        'product.brand', string="Brand", required=True, ondelete='cascade', index=True,
        help="The maker running the offer. Every product carrying this brand "
             "is included, unless you narrow it below.",
    )
    product_ids = fields.Many2many(
        'product.template', string="Only These Products",
        domain="[('brand_id', '=', brand_id)]",
        help="Leave EMPTY for the whole brand, which is the usual case. Name "
             "products here only when the offer covers part of the range: "
             "then nothing else of that brand is discounted.",
    )
    discount_percent = fields.Float(
        string="Discount %", required=True, default=10.0,
        help="Percentage off the selling price, e.g. 10 for ten percent off.",
    )
    date_start = fields.Date(
        string="Starts", required=True, default=fields.Date.context_today,
        help="First day the offer applies. Nothing is discounted before this.",
    )
    date_end = fields.Date(
        string="Ends", required=True,
        help="Last day the offer applies, and it counts. The morning after "
             "this date the tills go back to full price on their own, with "
             "nobody having to switch anything off.\n\n"
             "Set by the Duration buttons above, or type an exact date here "
             "for anything longer or shorter than those.",
    )
    duration_preset = fields.Selection(
        [('7', "1 Week"), ('15', "15 Days"), ('30', "1 Month"), ('custom', "Custom")],
        string="Duration", default='15', store=False,
        help="How long the offer runs, counted from Starts. Pick one and Ends "
             "is filled in for you -- for anything else, choose Custom and "
             "type the exact end date.",
    )

    @api.onchange('duration_preset', 'date_start')
    def _onchange_duration_preset(self):
        # A convenience for typing nothing, not a source of truth: this only
        # ever WRITES date_end, and is not itself stored, so it never fights
        # with someone who prefers to just type an exact date directly there.
        if self.duration_preset and self.duration_preset != 'custom':
            start = self.date_start or fields.Date.context_today(self)
            self.date_end = start + timedelta(days=int(self.duration_preset))
    company_id = fields.Many2one(
        'res.company', string="Branch", domain=TRADING_COMPANY_DOMAIN, index=True,
        help="Leave empty to run the offer at every branch, which is normal "
             "for a maker's own campaign. Name a branch only when one shop is "
             "running it alone.",
    )
    active = fields.Boolean(
        default=True,
        help="Untick to hide a finished offer without deleting it, so last "
             "season's campaigns stay on record.",
    )
    state = fields.Selection(
        [('scheduled', "Not started yet"), ('running', "Running now"),
         ('finished', "Finished")],
        compute='_compute_state', store=False,
        help="Worked out from today's date against the two dates above.",
    )
    product_count = fields.Integer(
        string="# Products", compute='_compute_product_count',
        help="How many items this offer actually covers today.",
    )

    @api.depends('date_start', 'date_end')
    def _compute_state(self):
        today = fields.Date.context_today(self)
        for campaign in self:
            if campaign.date_start and campaign.date_start > today:
                campaign.state = 'scheduled'
            elif campaign.date_end and campaign.date_end < today:
                campaign.state = 'finished'
            else:
                campaign.state = 'running'

    @api.depends('brand_id', 'product_ids')
    def _compute_product_count(self):
        for campaign in self:
            campaign.product_count = len(campaign._covered_products())

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
        """The products this offer applies to: the named ones, else the brand."""
        self.ensure_one()
        if self.product_ids:
            return self.product_ids
        if not self.brand_id:
            return self.env['product.template']
        return self.env['product.template'].search([('brand_id', '=', self.brand_id.id)])

    @api.constrains('discount_percent')
    def _check_discount_percent(self):
        for campaign in self:
            if not 0 < campaign.discount_percent <= 100:
                raise ValidationError(_(
                    "The discount on %(name)s is %(pct)s%%, which cannot be "
                    "right. Enter a number above 0 and no more than 100 -- "
                    "type 10 for ten percent off, not 0.1.",
                    name=campaign.name or _("this offer"),
                    pct=campaign.discount_percent,
                ))

    @api.constrains('date_start', 'date_end')
    def _check_dates(self):
        for campaign in self:
            if campaign.date_start and campaign.date_end and campaign.date_end < campaign.date_start:
                raise ValidationError(_(
                    "%(name)s is set to end on %(end)s, before it starts on "
                    "%(start)s, so it would never run at all.",
                    name=campaign.name or _("This offer"),
                    end=campaign.date_end, start=campaign.date_start,
                ))

    # ------------------------------------------------------------------
    # Point of Sale
    # ------------------------------------------------------------------
    @api.model
    def _load_pos_data_domain(self, data, config):
        """Every campaign for this branch, NOT narrowed to "live today".

        POS only reloads records that changed since the last sync (see
        pos.load.mixin._server_date_to_domain), and a campaign's write_date
        does not move on the day it starts or ends -- nobody edits the record,
        the calendar just turns over. Filtering by date here would mean a
        campaign that goes live overnight, or one that quietly expires, never
        reaches a session that was already open: exactly backwards from what a
        time-boxed offer needs.

        Loyalty programs solve the same problem the same way (see
        pos_loyalty/models/loyalty_program.py): ship every record for the
        config and let the browser compare today's date against date_start /
        date_end at the moment a discount is actually computed.
        """
        return [
            '|', ('company_id', '=', False),
                 ('company_id', '=', config.company_id.id),
        ]

    @api.model
    def _load_pos_data_fields(self, config):
        return ['id', 'name', 'brand_id', 'discount_percent', 'date_start', 'date_end']

    @api.model
    def _load_pos_data_read(self, records, config):
        """Ship the product ids each offer covers, resolved on the server.

        The till cannot work them out for itself: narrowing by product is
        optional, so "everything of this brand" has to be expanded here, and
        product.template.brand_id is not part of the POS payload.
        """
        read_records = super()._load_pos_data_read(records, config)
        covered = {c.id: c._covered_products().ids for c in records.sudo()}
        for row in read_records:
            row['_product_tmpl_ids'] = covered.get(row['id'], [])
        return read_records
