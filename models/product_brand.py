from odoo import api, fields, models


class ProductBrand(models.Model):
    _name = 'product.brand'
    _description = "Product Brand"
    _order = 'name'

    name = fields.Char(string="Brand", required=True, translate=True)
    active = fields.Boolean(default=True)
    description = fields.Text()
    image = fields.Image(string="Logo", max_width=512, max_height=512)
    product_count = fields.Integer(
        string="# Products", compute='_compute_product_count',
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
