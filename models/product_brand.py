from odoo import api, fields, models


class ProductBrand(models.Model):
    _name = 'product.brand'
    _description = "Product Brand"
    _inherit = ['pos.load.mixin']
    _order = 'name'

    # brand_id is shipped to the till on every product.product (see
    # product_product._load_pos_data_fields). A relation is only usable there if
    # its COMODEL is loaded too: the client builds typed models from
    # pos_session._load_pos_data_relations and links every many2one against the
    # loaded registry, so a brand_id pointing at a model the client never
    # received is a dangling reference. That stayed invisible for as long as
    # barely any product carried a brand, and broke the catalogue the moment a
    # real branded one arrived.

    name = fields.Char(
        string="Brand", required=True, translate=True,
        help="The maker or label printed on the product, for example Nestle or "
             "Samsung. Staff can search and filter the catalogue by it, and no "
             "two brands may share the same name.",
    )
    company_id = fields.Many2one(
        'res.company', string="Branch", index=True,
        help="Branch that stocks this brand. Leave empty to offer it at every "
             "branch, which is right for most brands.",
    )
    active = fields.Boolean(
        default=True,
        help="Untick to stop this brand being offered on new products, for "
             "instance when you drop the range. Products already tagged with it "
             "keep the brand and past sales figures are unaffected.",
    )
    description = fields.Text(
        help="Your own notes about the brand, such as which supplier carries it "
             "or what the range covers. It is for internal reference and is "
             "never printed on a receipt.",
    )
    image = fields.Image(
        string="Logo", max_width=512, max_height=512,
        help="Optional logo shown on the brand's card in the brand list, purely "
             "to help staff recognise it at a glance. It does not appear on "
             "receipts or price tags.",
    )
    product_count = fields.Integer(
        string="# Products", compute='_compute_product_count',
        help="How many products currently carry this brand. Click the number to "
             "open that list of products.",
    )

    _name_uniq = models.Constraint(
        'unique(name)',
        "A brand with this name already exists.",
    )

    def _compute_product_count(self):
        counts = dict(self.env['product.template']._read_group(
            domain=[('brand_id', 'in', self.ids)],
            groupby=['brand_id'],
            aggregates=['__count'],
        ))
        for brand in self:
            brand.product_count = counts.get(brand, 0)

    def action_view_products(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': self.name,
            'res_model': 'product.template',
            'view_mode': 'kanban,list,form',
            'domain': [('brand_id', '=', self.id)],
            'context': {'default_brand_id': self.id},
        }

    @api.model
    def _load_pos_data_domain(self, data, config):
        return [
            ('active', '=', True),
            '|', ('company_id', '=', False), ('company_id', '=', config.company_id.id),
        ]

    @api.model
    def _load_pos_data_fields(self, config):
        # Only what the till could show or search on; the brand's own reporting
        # fields are backend-side and would just inflate the session payload.
        return ['id', 'name']
