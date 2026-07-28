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
    'version': '19.0.2.7.0',
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
        'data/pos_retail_price_reason_data.xml',
        # Permission catalog seed: must load before all views because the
        # menus file references the auto-created perm_*_res_groups xmlids.
        'data/pos_retail_access_permission_data.xml',
        'data/pos_retail_access_permission_crud_data.xml',
        'data/pos_retail_access_role_data.xml',
        'data/pos_retail_package_data.xml',
        'views/product_brand_views.xml',
        'views/pos_retail_inventory_movement_views.xml',
        'views/pos_retail_expense_views.xml',
        'views/pos_retail_discount_role_views.xml',
        'views/pos_retail_discount_reason_views.xml',
        'views/pos_retail_return_reason_views.xml',
        'views/pos_retail_price_reason_views.xml',
        'views/pos_retail_discount_log_views.xml',
        'report/pos_retail_discount_log_report.xml',
        'report/pos_retail_receipt_report.xml',
        'report/pos_retail_goods_receipt_report.xml',
        # After the report: the template attaches the A4 report by xmlid.
        'data/pos_retail_mail_template_data.xml',
        'views/pos_order_views.xml',
        'views/stock_picking_views.xml',
        'views/product_template_views.xml',
        'views/product_uom_views.xml',
        'views/pos_retail_package_report_views.xml',
        'report/pos_retail_package_label_report.xml',
        'views/product_supplierinfo_views.xml',
        'views/purchase_report_views.xml',
        'views/pos_order_report_views.xml',
        'views/pos_retail_return_report_views.xml',
        'views/pos_retail_price_report_views.xml',
        'views/pos_retail_customer_ledger_views.xml',
        'views/sale_order_views.xml',
        'views/account_move_views.xml',
        'views/pos_membership_level_views.xml',
        'views/ir_module_views.xml',
        'views/res_country_views.xml',
        'views/res_partner_views.xml',
        'views/pos_config_views.xml',
        'views/pos_retail_dashboard_views.xml',
        'views/pos_retail_access_role_views.xml',
        'views/pos_retail_access_permission_views.xml',
        'views/pos_retail_menus.xml',
        'views/res_users_views.xml',
        'views/login_templates.xml',
        'views/layout_templates.xml',
    ],
    'demo': [
        'demo/pos_retail_demo.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'pos_retail/static/src/dashboard/**/*',
            'pos_retail/static/src/backend/backend_theme.scss',
            'pos_retail/static/src/backend/chatter.xml',
            'pos_retail/static/src/backend/form_save_button.xml',
            'pos_retail/static/src/backend/about.xml',
            'pos_retail/static/src/backend/hide_messaging.js',
            'pos_retail/static/src/backend/hide_odoo_links.js',
            'pos_retail/static/src/backend/import_button.js',
            'pos_retail/static/src/backend/import_button.xml',
            'pos_retail/static/src/backend/sidebar.js',
            'pos_retail/static/src/backend/sidebar.xml',
            'pos_retail/static/src/backend/sidebar.scss',
        ],
        # The sign-in page renders through web.frontend_layout, so its styling
        # belongs to the frontend bundle rather than the backend one.
        'web.assets_frontend': [
            'pos_retail/static/src/login/login.scss',
        ],
        # Receipt PDF styling must be in both bundles: _common drives the HTML
        # preview, _pdf is what wkhtmltopdf actually loads.
        'web.report_assets_common': [
            'pos_retail/static/src/report/pos_retail_receipt_report.scss',
        ],
        'web.report_assets_pdf': [
            'pos_retail/static/src/report/pos_retail_receipt_report.scss',
        ],
        'point_of_sale._assets_pos': [
            'pos_retail/static/src/receipt/receipt.js',
            'pos_retail/static/src/receipt/receipt.xml',
            'pos_retail/static/src/receipt/receipt_header.xml',
            'pos_retail/static/src/receipt/receipt.scss',
            'pos_retail/static/src/overrides/negative_stock_warning.js',
            'pos_retail/static/src/overrides/order_discount.js',
            'pos_retail/static/src/overrides/order_discount.xml',
            'pos_retail/static/src/overrides/pos_theme.scss',
            'pos_retail/static/src/overrides/pos_theme.xml',
            'pos_retail/static/src/overrides/partner_quick_create.js',
            'pos_retail/static/src/overrides/partner_quick_create.xml',
            'pos_retail/static/src/utils/manager_pin.js',
            'pos_retail/static/src/overrides/price_popup.js',
            'pos_retail/static/src/overrides/price_popup.xml',
            'pos_retail/static/src/overrides/price_override.js',
            'pos_retail/static/src/overrides/package_pricing.js',
            'pos_retail/static/src/overrides/customer_profile.js',
            'pos_retail/static/src/overrides/customer_profile.xml',
            'pos_retail/static/src/overrides/customer_profile.scss',
            'pos_retail/static/src/overrides/customer_profile_button.js',
            'pos_retail/static/src/overrides/customer_profile_button.xml',
            'pos_retail/static/src/overrides/credit_limit.js',
            'pos_retail/static/src/overrides/product_card.js',
            'pos_retail/static/src/overrides/product_card.xml',
            'pos_retail/static/src/overrides/orderline_qty.js',
            'pos_retail/static/src/overrides/orderline_qty.xml',
            'pos_retail/static/src/overrides/backend_login.js',
            'pos_retail/static/src/overrides/payment_screen.xml',
            'pos_retail/static/src/overrides/return_refund.js',
            'pos_retail/static/src/overrides/return_no_receipt_popup.js',
            'pos_retail/static/src/overrides/return_no_receipt_popup.xml',
            'pos_retail/static/src/overrides/return_no_receipt.js',
            'pos_retail/static/src/overrides/return_no_receipt.xml',
            'pos_retail/static/src/overrides/quotation.js',
            'pos_retail/static/src/overrides/quotation.xml',
        ],
        # The customer display page is served from its own bundle, separate
        # from the main POS assets.
        'point_of_sale.customer_display_assets': [
            'pos_retail/static/src/customer_display/customer_display.xml',
        ],
    },
    'installable': True,
    'application': False,
    'post_init_hook': '_pos_retail_post_init',
}
