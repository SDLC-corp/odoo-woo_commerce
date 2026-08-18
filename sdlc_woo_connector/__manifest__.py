{
    "name": "Odoo WooCommerce Connector",
    "version": "19.0.1.0.0",
    "category": "Sales",
    "summary": "WooCommerce Odoo integration for Odoo 19: two-way sync of products, "
               "orders, customers, inventory, categories and coupons via signed "
               "webhooks, scheduled actions and field mapping. Multi-store, AI.",
    "description": """
    Odoo WooCommerce Connector
    ==========================

    Connect one or more WooCommerce stores to Odoo and keep your catalog, sales and
    customers up to date without re-entering data by hand. This WooCommerce Odoo
    integration works through real-time webhooks, scheduled actions and on-demand
    manual sync, so you decide how WooCommerce and Odoo stay aligned.

    Connection and multi-store
    --------------------------
    * Multi-store WooCommerce instance management: connect several WooCommerce stores to one Odoo database.
    * WooCommerce API connection management with consumer key / consumer secret and one-click connection testing.
    * Two-way WooCommerce to Odoo synchronization, with per-entity control over direction and timing.
    * Open any synced product directly in the WooCommerce admin from Odoo.

    Products and catalog
    --------------------
    * Bulk product import, single product import by WooCommerce ID, and product export / update back to WooCommerce.
    * SKU based product matching, so re-running a sync updates the right product instead of creating duplicates.
    * Product category synchronization, product tag creation during import, and product brand management.
    * Product variants, attributes, images and pricing carried across in both directions.

    Orders
    ------
    * Bulk order import and single order import by WooCommerce ID.
    * WooCommerce order line synchronization and conversion into Odoo sales orders.
    * Order status synchronization, order billing data synchronization and scheduled order status refresh.
    * Duplicate order cleanup, so the same WooCommerce order is never imported twice per instance.

    Customers, categories and coupons
    ---------------------------------
    * Customer import, customer create / update back to WooCommerce, and customer creation from order billing data.
    * Guest customer handling, so guest checkouts still produce a usable Odoo contact.
    * Category import, category export / update and category product count.
    * Coupon import and export with discount type, usage limit and expiry date synchronization.

    Inventory
    ---------
    * Inventory synchronization covering WooCommerce stock quantity and stock status.
    * Multi-instance inventory refresh across every connected store.

    Field mapping
    -------------
    * Generic, product, customer, order and category field mapping.
    * Automatic field mapping, nested WooCommerce field mapping and live field-mapping validation against a real sample.
    * Protected core field mapping, so critical fields cannot be remapped by accident.

    Sync control and automation
    ---------------------------
    * Import by WooCommerce ID, import by date range, manual record synchronization and sync preview before committing.
    * WooCommerce webhooks with HMAC-SHA256 signature verification for products, customers, orders, categories and coupons.
    * Order status webhook processing for near-instant status changes.
    * Scheduled automatic synchronization through standard Odoo scheduled actions, with per-entity hourly, daily, weekly or monthly intervals.
    * Centralized eCommerce management: real-time data synchronization, accurate inventory management, reduced manual work and faster order processing.

    Reporting and monitoring
    ------------------------
    * Synchronization reports and report lines, webhook reports and webhook logs.
    * Sales reports, order reports, cancelled order reports and mapping reports.
    * Synchronization status tracking, synchronization timeline, queue monitor, operations dashboard and connection health logs.

    Dashboard and analytics
    -----------------------
    * Main WooCommerce dashboard with totals and KPIs, recent orders, payment breakdown and order status breakdown.
    * Revenue, product and category analytics through the WooCommerce Analytics API, with a local analytics fallback when the remote API is slow or unavailable.
    * Real-time dashboard refresh events.

    Built-in AI
    -----------
    * AI sales insights and AI inventory insights, stored against the records they describe.
    * AI product content assistant: product description generation, short description generation, SEO content improvement and product tag suggestions.
    * AI chatbot assistant and an AI sync error assistant that explains failures in plain language.
    * AI provider configuration with OpenAI-compatible provider support, your own API key, and a graceful fallback when the provider is unavailable.

    Shipping and delivery
    ---------------------
    * WooCommerce settings integration, shipping menu, delivery order integration and WooCommerce tracking.

    Every sync is logged and errors are recorded, so you can check the status of
    each WooCommerce store from one place. The connector fits B2B, electronics,
    fashion, food, health and home and furniture stores.

    Support
    -------
    For setup help, documentation and support, contact SDLC Corp.
    """,
    "author": "SDLC Corp",
    "maintainer": "SDLC Corp",
    "company": "SDLC Corp",
    "website": "https://sdlccorp.com/products/odoo-woocommerce-connector/",
    "support": "support@sdlccorp.com",
    "license": "OPL-1",
    "price": 149.99,
    "currency": 'USD',
    "images": ["static/description/banner.gif"],
    "depends": [
        "base",
        "web",
        "bus",
        "product",
        "sale_management",
        "contacts",
        "stock",
        "stock_delivery",
        "mail",
    ],
    "data": [
        "security/ir.model.access.csv",
        "data/cron.xml",
        "views/woo_instance_view.xml",
        "views/woo_import_by_id_wizard_view.xml",
        "views/woo_import_date_range_wizard_view.xml",
        "views/woo_sync_preview_view.xml",
        "views/woo_manual_record_sync_views.xml",
        "views/woo_connection_health_log_view.xml",
        "views/woo_auto_mapping_views.xml",
        "views/woo_field_mapping_views.xml",
        "views/product_template_woo_view.xml",
        "views/product_brand_view.xml",
        "views/woo_category_sync_view.xml",
        "views/woo_coupon_sync_view.xml",
        "views/woo_product_sync_view.xml",
        "views/woo_product_sync_form.xml",
        "views/woo_ai_content_wizard_views.xml",
        "views/woo_customer_sync_view.xml",
        "views/woo_order_sync_view.xml",
        "views/woo_report_view.xml",
        "views/woo_queue_monitor_view.xml",
        "views/woo_webhook_log_view.xml",
        "views/woo_sync_timeline_view.xml",
        "views/woo_sales_report.xml",
        "views/woo_order_report.xml",
        "views/woo_inventory_views.xml",
        "views/woo_res_config_settings_view.xml",
        "data/woo_order_cron.xml",
        "views/woo_sync_dashboard_view.xml",
        "views/woo_actions.xml",
        "views/menu.xml",
    ],
    "assets": {
        "web.assets_backend": [
            "sdlc_woo_connector/static/src/xml/chatbot.xml",
            "sdlc_woo_connector/static/src/js/chatbot.js",
            "sdlc_woo_connector/static/src/scss/chatbot.scss",
            "sdlc_woo_connector/static/src/xml/woo_field_help_panel.xml",
            "sdlc_woo_connector/static/src/js/woo_field_help_panel.js",
            "sdlc_woo_connector/static/src/css/woo_field_help_panel.css",
            "sdlc_woo_connector/static/src/xml/woo_dashboard_templates.xml",
            "sdlc_woo_connector/static/src/js/woo_dashboard.js",
            "sdlc_woo_connector/static/src/css/woo_dashboard.css",
            "sdlc_woo_connector/static/src/css/woo_instance_kanban.css",
            "sdlc_woo_connector/static/src/css/woo_product_list.css",
        ],
    },
    "installable": True,
    "application": True,
    "auto_install": False,
}
