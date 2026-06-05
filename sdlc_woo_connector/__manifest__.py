{
    "name": "WooCommerce Odoo Connector",
    "version": "19.0.1.0.0",
    "category": "Sales",
    "summary": "Two-way WooCommerce Odoo integration to sync products, orders, "
               "customers, inventory, categories and coupons using webhooks, "
               "scheduled jobs and manual sync.",
    "description": """
    WooCommerce Odoo Connector
    ==========================

    Connect one or more WooCommerce stores to Odoo and keep your catalog, sales and
    customers up to date without re-entering data by hand. The connector works
    through real-time webhooks, scheduled (cron) jobs and on-demand manual sync, so
    you can decide how WooCommerce and Odoo stay aligned.

    Key features
    ------------
    * Two-way sync between WooCommerce and Odoo (import from Woo and push changes back to Woo).
    * Products and categories: bulk and single import, SKU based product matching, tag and category creation, and product updates pushed back to WooCommerce.
    * Orders: import WooCommerce orders with their order lines, push order status updates, and convert synced orders into Odoo sale orders.
    * Customers: import customers and create them automatically from order billing data, including guest checkout handling and push back to Woo.
    * Coupons: import and export coupons with discount type, usage limits and expiry dates.
    * Inventory: sync stock levels and stock status from WooCommerce.
    * Multi-store: manage several WooCommerce instances from one Odoo database.
    * Real-time webhooks: signed (HMAC-SHA256) endpoints for products, customers, orders, categories and coupons.
    * Scheduled automation: per-entity auto sync with hourly, daily, weekly or monthly intervals.
    * Custom field mapping: map WooCommerce fields to Odoo fields, including nested keys, with protected core fields and a live sample test.
    * Reports and monitoring: sync dashboard, sync reports, webhook logs, connection health and a sync timeline.

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
    "support": "sales@sdlccorp.com",
    "license": "OPL-1",
    'price': 19.99,
    'currency': 'USD',
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
        "views/product_action.xml",
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
        "views/woo_dashboard_action.xml",
        "views/woo_actions.xml",
        "views/menu.xml",
    ],
    "assets": {
        "web.assets_backend": [
            "woo_connector/static/src/xml/chatbot.xml",
            "woo_connector/static/src/js/chatbot.js",
            "woo_connector/static/src/scss/chatbot.scss",
            "woo_connector/static/src/xml/woo_field_help_panel.xml",
            "woo_connector/static/src/js/woo_field_help_panel.js",
            "woo_connector/static/src/css/woo_field_help_panel.css",
            "woo_connector/static/src/xml/woo_dashboard_templates.xml",
            "woo_connector/static/src/js/woo_dashboard.js",
            "woo_connector/static/src/css/woo_dashboard.css",
            "woo_connector/static/src/css/woo_instance_kanban.css",
            "woo_connector/static/src/css/woo_product_list.css",
        ],
    },
    "installable": True,
    "application": True,
    'auto_install': False,
}
