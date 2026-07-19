# Part of the pos_retail project. See README for details.
{
    'name': "POS Retail",
    'summary': "Retail POS extensions: brands, vendors, pricing, analytics, expenses, order discounts",
    'description': """
POS Retail
==========
Custom extensions on top of Odoo Point of Sale for the retail MVP:

* Product Brand (categorise products by brand)
* Customer birthday + membership level
* Vendor management: preferred vendor per product, purchase price history, 7 vendor reports
* Product pricing: wholesale/minimum/MRP prices, profit & margin, discount settings, validation
* Real-time inventory movement audit trail per completed sale (with negative-stock warnings)
* Business analytics dashboard: sales/financial/inventory KPIs, custom date range, drill-throughs
* Lean business expenses tracking (rent, electricity, salaries, ...) with category reports
* Order-level discounts (fixed or %) with role-based limits, manager PIN approval,
  mandatory reasons, round-off cap, immutable audit log, 9 reports + PDF summary

This module only adds the gaps that Odoo core does not cover out of the box.
Inventory, purchasing, vendors, loyalty/promotions and cash control are handled
by the standard apps (stock, purchase, account, loyalty, pos_loyalty, hr).
    """,
    'author': "pos_retail",
    'category': 'Sales/Point of Sale',
    'version': '19.0.2.3.0',
    'license': 'LGPL-3',
    'depends': [
        # Core POS + the standard apps that deliver ~85% of the roadmap.
        # Depending on them here makes `-i pos_retail` install the whole stack.
        'point_of_sale',
        'contacts',
        'pos_loyalty',      # promotions, coupons, gift cards, loyalty points in POS
        'pos_discount',     # order-level % discount button in POS (product-screen);
                            # pos_retail adds a Fixed Amount mode + limits/approval on the payment screen
        'pos_hr',           # cashier login, employee on session
        'product_expiry',   # expiry/lot tracking
        'purchase',         # purchase orders + vendor bills (pulls stock/account)
        'pos_sale',         # quotations: create a sale.order from POS and settle
                            # it back for payment (pulls sale + sale_management)
    ],
    'data': [
        'security/ir.model.access.csv',
        'data/pos_membership_level_data.xml',
        'data/pos_retail_discount_role_data.xml',
        'data/pos_retail_discount_reason_data.xml',
        'data/pos_retail_return_reason_data.xml',
        'views/product_brand_views.xml',
        'views/pos_retail_inventory_movement_views.xml',
        'views/pos_retail_expense_views.xml',
        'views/pos_retail_discount_role_views.xml',
        'views/pos_retail_discount_reason_views.xml',
        'views/pos_retail_return_reason_views.xml',
        'views/pos_retail_discount_log_views.xml',
        'report/pos_retail_discount_log_report.xml',
        'views/product_template_views.xml',
        'views/product_supplierinfo_views.xml',
        'views/purchase_report_views.xml',
        'views/pos_order_report_views.xml',
        'views/pos_retail_return_report_views.xml',
        'views/account_move_views.xml',
        'views/pos_membership_level_views.xml',
        'views/res_partner_views.xml',
        'views/pos_config_views.xml',
        'views/pos_retail_dashboard_views.xml',
        'views/pos_retail_menus.xml',
        'views/res_users_views.xml',
    ],
    'demo': [
        'demo/pos_retail_demo.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'pos_retail/static/src/dashboard/**/*',
            'pos_retail/static/src/backend/backend_theme.scss',
        ],
        # The sign-in page renders through web.frontend_layout, so its styling
        # belongs to the frontend bundle rather than the backend one.
        'web.assets_frontend': [
        ],
        'point_of_sale._assets_pos': [
            'pos_retail/static/src/receipt/receipt.js',
            'pos_retail/static/src/receipt/receipt.xml',
            'pos_retail/static/src/receipt/receipt_header.xml',
            'pos_retail/static/src/overrides/negative_stock_warning.js',
            'pos_retail/static/src/overrides/order_discount.js',
            'pos_retail/static/src/overrides/order_discount.xml',
            'pos_retail/static/src/overrides/pos_theme.scss',
            'pos_retail/static/src/overrides/pos_theme.xml',
            'pos_retail/static/src/overrides/partner_quick_create.js',
            'pos_retail/static/src/overrides/partner_quick_create.xml',
            'pos_retail/static/src/overrides/orderline_qty.js',
            'pos_retail/static/src/overrides/orderline_qty.xml',
            'pos_retail/static/src/overrides/backend_login.js',
            'pos_retail/static/src/overrides/receipt_screen.xml',
            'pos_retail/static/src/overrides/return_refund.js',
            'pos_retail/static/src/overrides/return_no_receipt_popup.js',
            'pos_retail/static/src/overrides/return_no_receipt_popup.xml',
            'pos_retail/static/src/overrides/return_no_receipt.js',
            'pos_retail/static/src/overrides/return_no_receipt.xml',
        ],
    },
    'installable': True,
    'application': False,
    'post_init_hook': '_pos_retail_post_init',
}
