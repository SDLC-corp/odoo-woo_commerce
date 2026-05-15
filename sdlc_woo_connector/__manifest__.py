{
    'name': 'Odoo WooCommerce Connector',
    'version': '18.0.1.0.0',
    'summary': 'Connect Odoo with WooCommerce to sync products, orders, customers, inventory, coupons, categories, and sales reports',
    'description': """
    Odoo WooCommerce Connector
    ==========================

    Odoo WooCommerce Connector helps businesses connect their WooCommerce store with Odoo for smooth eCommerce operations. It allows users to manage product data, orders, customers, inventory, categories, coupons, and sales reports from Odoo with structured WooCommerce synchronization.

    This connector is useful for online stores, retailers, distributors, D2C brands, and eCommerce businesses that want to reduce manual work, avoid duplicate data entry, and keep Odoo and WooCommerce data aligned.

    Key Features
    ------------
    * Connect Odoo with WooCommerce store
    * Sync products from Odoo to WooCommerce
    * Manage WooCommerce product categories
    * Sync WooCommerce customers into Odoo
    * Import WooCommerce orders into Odoo
    * Track and manage WooCommerce inventory
    * Sync WooCommerce coupons
    * Configure WooCommerce field mapping
    * View WooCommerce sales and order reports
    * Use dashboard for quick store performance insights
    * Automate order synchronization using scheduled cron jobs
    * Manage WooCommerce settings directly from Odoo

    Business Benefits
    -----------------
    * Reduce manual data entry between Odoo and WooCommerce
    * Improve eCommerce order management
    * Keep product and inventory data organized
    * Centralize customer and sales information in Odoo
    * Save time with automated synchronization
    * Improve operational accuracy for online sales
    * Support faster order processing and reporting

    Best For
    --------
    * WooCommerce store owners
    * Odoo users managing online sales
    * eCommerce businesses
    * Retail and D2C brands
    * Wholesale and distribution companies
    * Businesses using Odoo as their ERP backend

    Odoo WooCommerce Connector is designed to simplify WooCommerce integration with Odoo and help businesses manage eCommerce workflows from one centralized system.
    """
    'author': 'SDLC Corp',
    'support': 'support@sdlccorp.com',
    'maintainer': 'SDLC Corp',
    'auto_install': False,
    'sequence': 1,
    'category': 'Sales'
    'website': 'https://sdlccorp.com/',
    'price': 19.99,
    'currency': 'USD',
    'license': 'OPL-1',
    'depends': ["base",
                "web",
                "bus",
                "product",
                "sale_management",
                "contacts",
                "stock",
                "stock_delivery",
                "mail",
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
        'views/woo_ai_content_wizard_views.xml',
        'views/woo_customer_sync_view.xml',
        'views/woo_order_sync_view.xml',
        'views/woo_report_view.xml',
        'views/woo_sales_report.xml',
        'views/woo_order_report.xml',
        "views/woo_inventory_views.xml",
        "views/woo_res_config_settings_view.xml",
        "data/woo_order_cron.xml",

        "views/woo_dashboard_action.xml",

        # 4️⃣ ACTIONS (must be AFTER models + views)
        'views/woo_actions.xml',

        # 5️⃣ MENUS (LAST always)
        'views/menu.xml',
    ],
    "assets": {
        "web.assets_backend": [
            "sdlc_woo_connector/static/src/xml/chatbot.xml",
            "sdlc_woo_connector/static/src/js/chatbot.js",
            "sdlc_woo_connector/static/src/scss/chatbot.scss",
            "sdlc_woo_connector/static/src/xml/woo_dashboard_templates.xml",
            "sdlc_woo_connector/static/src/js/woo_dashboard.js",
            "sdlc_woo_connector/static/src/css/woo_dashboard.css",
            "sdlc_woo_connector/static/src/css/woo_instance_kanban.css",
            "sdlc_woo_connector/static/src/css/woo_product_list.css",
        ],
    },

    'installable': True,
    'application': True,
    "images":["static/description/banner.gif"],
}
