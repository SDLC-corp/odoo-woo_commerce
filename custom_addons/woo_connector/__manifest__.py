{
    'name': 'Odoo WooCommerce Connector',
    'version': '1.0.0',
    'summary': 'Sync products from Odoo to WooCommerce',
    'category': 'Sales',
    'author': 'Your Company',
    'depends': ["base",
                "web",
                "product",
                "sale_management",
                "contacts",
                "stock",
                "stock_delivery",
                ],
    'data': [
        # 1️⃣ SECURITY FIRST
        'security/ir.model.access.csv',

        'views/product_action.xml',
        "data/cron.xml",

        # 2️⃣ CORE MODELS VIEWS (no actions yet)
        'views/woo_instance_view.xml',
        "views/woo_field_mapping_views.xml",

        # 3️⃣ DATA MODELS VIEWS
        "views/product_template_woo_view.xml",
        'views/woo_category_sync_view.xml',
        'views/woo_coupon_sync_view.xml',
        'views/woo_product_sync_view.xml',
        'views/woo_product_sync_form.xml',
        'views/woo_customer_sync_view.xml',
        'views/woo_order_sync_view.xml',
        'views/woo_report_view.xml',
        'views/woo_sales_report.xml',
        'views/woo_order_report.xml',
        "views/woo_inventory_views.xml",
        "data/woo_order_cron.xml",

        "views/woo_dashboard_action.xml",

        # 4️⃣ ACTIONS (must be AFTER models + views)
        'views/woo_actions.xml',

        # 5️⃣ MENUS (LAST always)
        'views/menu.xml',
    ],
    "assets": {
        "web.assets_backend": [
            "woo_connector/static/src/xml/woo_dashboard_templates.xml",
            "woo_connector/static/src/js/woo_dashboard.js",
            "woo_connector/static/src/js/woo_list_click_guard.js",
            "woo_connector/static/src/css/woo_dashboard.css",
            "woo_connector/static/src/css/woo_instance_kanban.css",
            "woo_connector/static/src/css/woo_product_list.css",
        ],
    },

    'installable': True,
    'application': True,
}
