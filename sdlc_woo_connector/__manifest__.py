{
    'name': 'Odoo WooCommerce Connector',
    'version': '18.0.1.0.0',
    'summary': 'Odoo WooCommerce Connector for real-time two-way WooCommerce Odoo integration - sync products, orders, customers, inventory, coupons & categories via the WooCommerce REST API, with webhooks, automated cron sync, field mapping, multi-store support, dashboards, reports & built-in AI',
    'description': """
    Odoo WooCommerce Connector - WooCommerce Odoo Integration & Sync
    ================================================================

    The Odoo WooCommerce Connector is a complete WooCommerce Odoo integration that keeps your
    WooCommerce store and Odoo in sync in real time. Connect one or more WooCommerce stores to a
    single Odoo database and manage products, categories, customers, orders, inventory, and coupons
    with reliable two-way (bidirectional) synchronization built on the official WooCommerce REST API.

    Import WooCommerce orders into Odoo, push Odoo products to WooCommerce, automate order status
    updates, and run your entire eCommerce back office from Odoo - with real-time webhooks, scheduled
    automatic sync, configurable field mapping, dashboards, reports, and built-in AI assistance.

    Why choose this WooCommerce connector for Odoo?
    -----------------------------------------------
    * Real-time, two-way synchronization between WooCommerce and Odoo
    * Built on the standard WooCommerce REST API - no custom WordPress plugin required
    * Connect multiple WooCommerce stores to one Odoo database (multi-store / multi-instance)
    * Built-in AI (insights, product content assistant, chatbot) - a step beyond a basic connector
    * Works with Odoo Community & Enterprise on Odoo Online, Odoo.sh, and On-Premise

    Product Synchronization
    -----------------------
    * Two-way product sync between Odoo and WooCommerce
    * Sync SKU, regular price and sale price
    * Sync product categories and product tags
    * Keep stock quantities aligned between Odoo and WooCommerce

    Order Management
    ----------------
    * Import WooCommerce orders into Odoo with full order lines
    * Two-way order status sync (processing, completed, cancelled, refunded, and more)
    * Automatic order status updates on a schedule
    * Cancelled-order reporting

    Customers, Categories & Coupons
    -------------------------------
    * Sync WooCommerce customers into Odoo contacts
    * Manage and sync WooCommerce product categories
    * Sync WooCommerce coupons and gift cards

    Inventory & Stock
    -----------------
    * Track and update WooCommerce inventory from Odoo
    * Keep stock levels accurate to reduce overselling

    Real-Time Webhooks & Automation
    -------------------------------
    * Near-instant sync via WooCommerce webhooks for products, customers, orders,
      categories, and gift cards
    * Scheduled background synchronization with configurable cron intervals
      (hourly, daily, weekly, or monthly per record type)
    * Sync logs, webhook reports, and status tracking to monitor and troubleshoot

    Field Mapping
    -------------
    * Configurable field mapping for products, customers, and categories
    * Map WooCommerce fields to the matching Odoo fields with full control

    Shipping & Fulfillment
    ----------------------
    * Manage delivery orders and shipment tracking
    * Keep fulfillment status aligned with WooCommerce

    Dashboards & Reports
    --------------------
    * Interactive dashboard with charts and store performance insights
    * Reports: sync reports, sales reports, cancelled orders, webhook reports,
      and field-mapping reports

    Built-in AI Assistance
    ----------------------
    * AI Sales & Inventory Insights generated from your store data
    * AI Product Content Assistant (descriptions, short descriptions, SEO text, tags)
    * Built-in AI chatbot assistant for WooCommerce operations
    * AI is optional and degrades gracefully when disabled or unavailable

    Keywords: WooCommerce Odoo connector, WooCommerce Odoo integration, sync WooCommerce with Odoo,
    import WooCommerce orders into Odoo, WooCommerce product sync, WooCommerce inventory sync,
    WooCommerce order sync, real-time WooCommerce integration, WooCommerce REST API, multi-store
    WooCommerce connector, eCommerce connector.

    Business Benefits
    -----------------
    * Reduce manual data entry between Odoo and WooCommerce
    * Improve eCommerce order management and fulfillment
    * Keep product, stock, and pricing data accurate across channels
    * Centralize customer and sales information in Odoo
    * Save time with real-time webhooks and automated synchronization
    * Gain insights faster with dashboards, reports, and AI assistance

    Best For
    --------
    * WooCommerce store owners and online retailers
    * eCommerce, D2C, and B2B brands
    * Wholesale and distribution companies
    * Dropshippers and multi-store sellers
    * Businesses using Odoo as their ERP backend

    Odoo WooCommerce Connector is designed to simplify WooCommerce integration with Odoo and help
    businesses manage eCommerce workflows from one centralized system.
    """,
    'author': 'SDLC Corp',
    'support': 'sales@sdlccorp.com',
    'maintainer': 'SDLC Corp',
    'auto_install': False,
    'sequence': 1,
    'category': 'Sales',
    'website': 'https://sdlccorp.com/products/odoo-woocommerce-connector/',
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
