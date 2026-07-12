# Part of the pos_retail project. See README for details.
{
    'name': "POS Retail",
    'summary': "Retail POS extensions: product brand, customer birthday & membership levels",
    'description': """
POS Retail
==========
Custom extensions on top of Odoo Point of Sale for the retail MVP:

* Product Brand (categorise products by brand)
* Customer birthday + membership level
* Groundwork for the branded dashboard, promotions and local payment methods

This module only adds the gaps that Odoo core does not cover out of the box.
Inventory, purchasing, vendors, loyalty/promotions and cash control are handled
by the standard apps (stock, purchase, account, loyalty, pos_loyalty, hr).
    """,
    'author': "pos_retail",
    'category': 'Sales/Point of Sale',
    'version': '19.0.1.0.0',
    'license': 'LGPL-3',
    'depends': [
        # Core POS + the standard apps that deliver ~85% of the roadmap.
        # Depending on them here makes `-i pos_retail` install the whole stack.
        'point_of_sale',
        'contacts',
        'pos_loyalty',      # promotions, coupons, gift cards, loyalty points in POS
        'pos_discount',     # order-level %/fixed discount button in POS
        'pos_hr',           # cashier login, employee on session
        'product_expiry',   # expiry/lot tracking
        'purchase',         # purchase orders + vendor bills (pulls stock/account)
    ],
    'data': [
        'security/ir.model.access.csv',
        'data/pos_membership_level_data.xml',
        'views/product_brand_views.xml',
        'views/product_template_views.xml',
        'views/pos_membership_level_views.xml',
        'views/res_partner_views.xml',
        'views/pos_config_views.xml',
        'views/pos_retail_dashboard_views.xml',
        'views/pos_retail_menus.xml',
    ],
    'demo': [
        'demo/pos_retail_demo.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'pos_retail/static/src/dashboard/**/*',
        ],
        'point_of_sale._assets_pos': [
            'pos_retail/static/src/receipt/receipt.js',
            'pos_retail/static/src/receipt/receipt.xml',
        ],
    },
    'installable': True,
    'application': False,
}
