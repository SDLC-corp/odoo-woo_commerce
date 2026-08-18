{
    'name': 'Odoo WooCommerce Connector',
    'version': '18.0.1.0.0',
    'summary': 'WooCommerce Odoo integration for Odoo 18: two-way sync of products, '
               'orders, customers, inventory, categories and coupons via signed '
               'webhooks, scheduled actions and field mapping. Multi-store, AI.',
    'description': """
    Odoo WooCommerce Connector
    ==========================

    The Odoo 18 WooCommerce Connector is a complete Odoo WooCommerce integration for stores that
    need a real WooCommerce ERP integration rather than a one-way importer. Connect one or more
    WooCommerce stores to a single Odoo database and manage products, categories, customers,
    orders, inventory and coupons with two-way synchronization built on the standard WooCommerce
    REST API.

    Import WooCommerce orders into Odoo, push Odoo products to WooCommerce, keep stock accurate on
    both sides, and run the whole WooCommerce Odoo sync from one back office. No custom WordPress
    plugin is required on your store.

    Multi-store WooCommerce instance management
    -------------------------------------------
    * Multiple WooCommerce store / instance support, each enabled or disabled independently.
    * Store URL, consumer key and consumer secret configuration, plus WordPress username and
      application password support where your host requires it.
    * Test Connection before you sync a single record.
    * Per-instance statistics: total products, total orders, total customers and total revenue.
    * Last synchronization tracking per instance and per record type.

    WooCommerce product sync and catalog
    ------------------------------------
    * Import products from WooCommerce into Odoo and push products from Odoo to WooCommerce.
    * Bulk product sync, or pull a single product by its WooCommerce product ID.
    * SKU based matching against existing Odoo products, linked to product.template.
    * Syncs name, SKU, regular price, sale price, description, short description, stock quantity,
      stock status, manage-stock flag, categories and tags.
    * Missing categories and tags are created automatically on import.
    * Open the matching Odoo product, or jump straight to the product in the WooCommerce admin.

    WooCommerce order sync
    ----------------------
    * Import WooCommerce orders in bulk, or pull an individual order by its WooCommerce order ID.
    * Order line synchronization with SKU and product matching.
    * Syncs customer information, billing details, payment method, order status, customer notes,
      order amount and currency.
    * Converts each WooCommerce order into a linked Odoo sales order.
    * Pushes order updates and status changes back to WooCommerce.
    * Duplicate order detection and cleanup per instance.
    * Scheduled WooCommerce order status synchronization.

    WooCommerce customer sync
    -------------------------
    * Import customers from WooCommerce and create or update customers back in WooCommerce.
    * Syncs name, email, phone and billing information.
    * Creates and updates customers automatically from WooCommerce orders.
    * Guest customer handling, identified by email, with a WooCommerce order count per contact.

    WooCommerce category and coupon sync
    ------------------------------------
    * Import WooCommerce categories, and create or update categories from Odoo.
    * Category parent relationship, slug, description and product count on both sides.
    * Import and export coupons with code, discount type, discount amount, usage limit,
      usage count, expiry date and status, with sync state tracked per record.

    WooCommerce inventory sync
    --------------------------
    * WooCommerce inventory synchronization by product and by instance.
    * SKU based inventory information, stock quantity, and in-stock / out-of-stock status.
    * Manage-stock support, including quantity handling for products where WooCommerce stock
      management is switched off.
    * Manual and multi-instance inventory refresh.

    Odoo WooCommerce field mapping
    ------------------------------
    * Separate, configurable mappings for products, orders, customers and categories.
    * WooCommerce field catalog with Odoo field selection.
    * Nested WooCommerce field support such as billing.email and other nested JSON values.
    * Live preview showing the WooCommerce value beside the Odoo value.
    * Test a mapping against real store data before you commit it.
    * Individual mappings can be enabled or disabled, and core identity fields are protected.

    WooCommerce webhooks and scheduled sync
    ---------------------------------------
    * WooCommerce webhook endpoint with HMAC SHA-256 signature validation and a configurable secret.
    * Product, customer, order, category and coupon webhooks, plus a separate order status webhook.
    * Automatic synchronization for products, customers, orders, categories and coupons.
    * Per-entity intervals: hourly, daily, weekly or monthly, with configurable hour, minute,
      weekday and day of month.
    * Automatic sync can be enabled or disabled per record type and per instance.

    WooCommerce dashboard and analytics in Odoo
    -------------------------------------------
    * WooCommerce dashboard inside Odoo with multi-instance filtering.
    * Total sales, orders, customers and products, plus recent orders.
    * Payment method breakdown and order status breakdown, with dashboard graphs.
    * WooCommerce Analytics API integration: daily gross sales, net sales, order count and
      items sold, plus revenue and units by product and by category.
    * Real-time dashboard refresh over the Odoo bus, with a local database fallback when the
      WooCommerce analytics endpoints are slow or unavailable.

    Built-in AI for WooCommerce
    ---------------------------
    * AI product content assistant: long description, short description, SEO title, SEO meta
      description and product tag suggestions, with selectable tone and an SEO mode.
    * Preview generated content before applying it to the product.
    * AI sales and inventory insights over a 7-day or 30-day window, stored with status and
      timestamp, covering restocking priorities and stock risk.
    * AI chatbot assistant that answers operational questions about orders, products, inventory
      and synchronization status.
    * OpenAI-compatible provider configuration: provider, model, API key, maximum tokens and a
      custom endpoint, with a graceful fallback that keeps the connector working when AI is off.

    Sync reports and monitoring
    ---------------------------
    * Synchronization reports with detailed report lines, per instance and per operation.
    * Manual, scheduled and webhook runs are recorded separately, with the WooCommerce reference,
      success or failure status and the error message.
    * Sales reports, order reports, cancelled order reports and inventory reports.
    * Per-record sync state, last sync time and last error message.

    Every sync is logged and errors are recorded, so you can check the status of each
    WooCommerce store from one place. The connector fits B2B, electronics, fashion, food,
    health, home and furniture stores.

    Support
    -------
    For setup help, documentation and support, contact SDLC Corp.
    """,
    'author': 'SDLC Corp',
    'support': 'support@sdlccorp.com',
    'maintainer': 'SDLC Corp',
    'auto_install': False,
    'sequence': 1,
    'category': 'Sales',
    'website': 'https://sdlccorp.com/products/odoo-woocommerce-connector/',
    'price': 129.99,
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
