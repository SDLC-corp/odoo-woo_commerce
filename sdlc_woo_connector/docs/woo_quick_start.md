# Woo Connector Quick Start

1. Install module `Odoo WooCommerce Connector` from Apps.
2. Open `WooCommerce > Instances` and create an instance.
3. Fill:
   - `Name`
   - `Shop URL`
   - `Consumer Key`
   - `Consumer Secret`
   - `WP Username` and `Application Password` (required by current Test Connection implementation)
4. Click `Test Connection`.
5. Run initial manual sync from instance:
   - `Sync Products`
   - `Sync Orders`
   - `Sync Categories`
   - `Sync Coupons`
   - `Sync Inventory`
6. Open `WooCommerce > WooCommerce Data` menus and verify records:
   - Products
   - Customers
   - Orders
   - Categories
7. Configure field mappings:
   - `WooCommerce > Field Mapping > Product/Customer/Category Field Mapping`
   - Add mapping records and click `Test Mapping`.
8. Configure webhooks in WooCommerce:
   - Target URL: `/woo/webhook`
   - Optional order status route: `/woo/webhook/order`
   - Set same secret as `webhook_secret` in instance.
9. Enable webhook flags and auto-sync flags in instance.
10. Monitor results from:
   - `WooCommerce > Reports > Sync Reports`
   - `WooCommerce > Reports > Webhook Reports`

AI setup (optional):
- Go to `Settings > General Settings > WooCommerce Connector > AI Features`.
- Set provider, API key, model, max tokens, endpoint.
- Use product form AI buttons (`Generate Description`, `Improve SEO Text`, etc.).

Cron jobs enabled by data files:
- `WooCommerce Auto Sync` every 15 minutes
- `Sync Woo Order Status` every 5 minutes
