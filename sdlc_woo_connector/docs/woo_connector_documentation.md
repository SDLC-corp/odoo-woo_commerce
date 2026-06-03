# WooCommerce to Odoo Connector Documentation

## 1. Overview
This module connects WooCommerce and Odoo for bi-directional operational sync with a Woo-first integration pattern:
- Odoo stores per-store connection settings in `woo.instance`.
- Woo data is synchronized into Odoo sync tables (`woo.product.sync`, `woo.order.sync`, `woo.customer.sync`, `woo.category.sync`, `woo.coupon.sync`, `woo.inventory`).
- Selected records can be pushed back to WooCommerce from Odoo forms.
- Webhooks can update Odoo in near real-time through `/woo/webhook` and `/woo/webhook/order`.
- Sync outcomes are logged in `woo.report` and `woo.report.line`.

Business purpose:
- Keep product, order, customer, category, coupon, and inventory data aligned.
- Let operations users monitor integration health from Odoo.
- Support manual sync, cron-based sync, and webhook-driven updates.

WooCommerce <-> Odoo concept:
- WooCommerce APIs are the source for pull sync.
- Odoo creates/updates local sync records and optionally related Odoo business records (for example `product.template`, `sale.order`).
- Mapping rules (`woo.field.mapping`) can map Woo payload keys into sync model fields.

## 2. Key Features
Implemented features found in code:
- Multi-instance Woo store configuration (`woo.instance`) with credentials and activation flag.
- Product sync:
  - Pull product list from Woo (`woo.instance.action_sync_products`).
  - Pull single product (`woo.product.sync.action_pull_from_woo`).
  - Push single product updates (`woo.product.sync.action_push_to_woo`).
- Order sync:
  - Pull orders (`woo.instance.action_sync_orders`).
  - Pull single order (`woo.order.sync.sync_from_woocommerce` / `action_pull_from_woo`).
  - Push order status and billing updates (`woo.order.sync.action_push_to_woo`).
  - Create Odoo sale order from synced Woo order lines (`woo.order.sync.action_create_sale_order`).
- Customer sync:
  - Pull customers (`woo.instance.action_sync_customers`).
  - Customer upsert while syncing orders (`_sync_customer_from_order`).
  - Push customer create/update (`woo.customer.sync.action_push_to_woo`).
- Category sync:
  - Pull categories (`woo.instance.action_sync_categories`).
  - Push category create/update (`woo.category.sync.action_push_to_woo`).
- Coupon sync:
  - Pull coupons (`woo.instance.action_sync_coupons`).
  - Push coupon create/update (`woo.coupon.sync.action_push_to_woo`).
- Inventory sync:
  - Build/refresh `woo.inventory` from Woo product stock (`woo.instance.sync_inventory_from_woo`, `woo.inventory.action_refresh_inventory`).
- Field mapping framework:
  - Per-instance and per-model mapping (`woo.field.mapping` + `woo.field` catalog).
  - Mapping test and sample payload based field discovery.
- Webhook integration:
  - Topic-based webhook handling for product/customer/order/category/coupon create/update.
  - Optional HMAC signature verification via `webhook_secret`.
  - Dedicated order status webhook route.
- Cron automation:
  - Global auto-sync cron (`woo.instance.cron_auto_sync`).
  - Order status cron (`woo.order.sync.cron_sync_woo_order_status`).
- Monitoring and logs:
  - Structured sync reports (`woo.report`, `woo.report.line`).
  - Sync state lock/status (`woo.sync.status`).
- Dashboard and analytics:
  - JSON dashboard endpoint and metrics model (`woo.dashboard`, `/woo/dashboard/data`).
  - Revenue/order/customer/product/category totals and breakdowns.
- AI features:
  - AI insights storage (`woo.ai.insight`).
  - AI product content wizard (`woo.ai.content.wizard`).
  - AI provider integration via configurable OpenAI-compatible endpoint (`woo_ai_provider.py`).
- Chatbot:
  - Simple intent-based JSON endpoint (`/ai/chatbot/message`) for connector data queries.

## 3. How It Works
Step 1: Connect WooCommerce Store  
- User creates a record in `WooCommerce > Instances`.
- `woo.instance` stores `shop_url`, `consumer_key`, `consumer_secret`, optional `wp_username`, `application_password`, and `webhook_secret`.
- `action_test_connection()` validates connectivity against Woo `system_status` endpoint using WP credentials.

Step 2: Configure Sync Rules  
- User enables webhook flags and auto-sync flags in the instance form.
- User defines field mappings in `Field Mapping` menus (`woo.field.mapping`) by selecting Woo field key and Odoo field.
- `woo.field.mapping` can fetch sample payload and create Woo field catalog (`woo.field`) using `fetch_sample_data()` methods.

Step 3: Run Sync (Manual / Automatic)  
- Manual sync buttons on `woo.instance` call:
  - `action_sync_products`
  - `action_sync_orders`
  - `action_sync_categories`
  - `action_sync_coupons`
  - `sync_inventory_from_woo`
- Automatic sync:
  - Cron `WooCommerce Auto Sync` calls `woo.instance.cron_auto_sync()` every 15 minutes.
  - Per-instance auto flags (`auto_product_sync`, `auto_order_sync`, etc.) decide which entities run.
  - Separate cron syncs order status every 5 minutes.
- Webhook sync:
  - `/woo/webhook` resolves instance, validates signature (if configured), routes by topic, and calls `woo.webhook.sync` methods.
  - `/woo/webhook/order` updates `woo_status` for an existing synced order.

Step 4: Monitor Logs  
- Every sync path writes report records through `_create_sync_report()` or webhook logger `_log_webhook()`.
- Users monitor:
  - `Reports > Sync Reports` (non-webhook)
  - `Reports > Webhook Reports` (webhook-only)
- `woo.sync.status` tracks lock (`syncing`), `last_sync`, and `last_error`.

## 4. Prerequisites
- Odoo version:
  - Module is in an Odoo 17 codebase (`odoo17`).  
  - Exact supported Odoo versions are not declared in manifest. **Needs confirmation**
- Required Odoo dependencies from `__manifest__.py`:
  - `base`, `web`, `bus`, `product`, `sale_management`, `contacts`, `stock`, `stock_delivery`, `mail`
- Python/runtime libraries used by code:
  - `woocommerce`, `requests`, `python-dateutil`
- WooCommerce requirements:
  - Store URL with REST API access.
  - Consumer key and consumer secret.
  - Optional WP username + application password for some endpoints/fallback auth.
  - Optional webhook secret for signature validation.
- User roles / access:
  - `base.group_system`: full access to `woo.instance` and `woo.sync.status`.
  - `base.group_user`: access to sync models, reports, dashboard, AI models.
  - Some access lines have empty `group_id`, meaning broad access scope. **Needs confirmation**

## 5. Installation
1. Place module in addons path (already at `custom_addons/woo_connector`).
2. Update Apps list in Odoo.
3. Install module `Odoo WooCommerce Connector`.
4. Confirm dependencies listed in manifest are installed.
5. Post-install:
   - Create at least one Woo instance.
   - Configure credentials and run `Test Connection`.
   - Configure mapping rules if needed.
   - Enable auto sync/webhooks as required.

## 6. Configuration
Menu path:
- `WooCommerce > Instances`
- `WooCommerce > Field Mapping > Product/Customer/Category Field Mapping`
- `Settings > General Settings > WooCommerce Connector > AI Features`

Instance/store configuration fields (`woo.instance`):
- Basic: `name`, `shop_url`, `active`
- API: `consumer_key`, `consumer_secret`
- Optional auth: `wp_username`, `application_password`
- Webhook security: `webhook_secret`
- Webhook event flags:
  - Product create/update
  - Customer create/update
  - Order create/update
  - Category create/update
  - Coupon create/update (`webhook_giftcard_*` fields)
- Auto sync flags and interval type:
  - Product/customer/order/category/coupon auto sync
  - Interval type (`hours`, `days`, `weeks`, `months`)
  - Time selectors (`auto_sync_hour`, `auto_sync_minute`, `auto_sync_weekday`, `auto_sync_month_day`)

Woo API setup:
- Store URL: `shop_url`
- REST keys: `consumer_key` and `consumer_secret`
- For test connection route in current implementation: `wp_username` + `application_password` are required by `action_test_connection`.

Mapping setup:
- In `Field Mapping`, create mappings by model (`product`, `order`, `customer`, `category`).
- Select `odoo_field_id` and `woo_field_key`.
- Use `Test Mapping` button to validate sample payload extraction.

AI configuration fields (`res.config.settings`):
- `woocommerce_ai_enabled`
- `woocommerce_ai_provider`
- `woocommerce_ai_api_key`
- `woocommerce_ai_model`
- `woocommerce_ai_max_tokens`
- `woocommerce_ai_endpoint`

## 7. Data Synchronization
### Product Sync
Import logic:
- Bulk import: `woo.instance.action_sync_products()` -> `fetch_products()` -> create/update `product.template` + `woo.product.sync`.
- Single import: `woo.product.sync.action_pull_from_woo()` for selected `woo_product_id`.

Export logic:
- `woo.product.sync.action_push_to_woo()` updates Woo product by ID.
- `product.template.action_woo_create/action_woo_update` are demo placeholders, not full API sync. **Needs confirmation** for production usage intent.

Primary fields synced (`woo.product.sync`):
- Identity: `woo_product_id`, `name`, `sku`, `product_tmpl_id`, `instance_id`
- Pricing: `list_price`, `sale_price`
- Inventory: `manage_stock`, `qty_available`, `stock_status`
- Classification: `category_ids`, `tag_ids`
- Content/meta: `description`, `short_description`, `published_date`, `synced_on`

### Order Sync
Import logic:
- Bulk: `woo.instance.action_sync_orders()` pulls `/orders` and upserts `woo.order.sync`.
- Single: `woo.order.sync.sync_from_woocommerce()` fetches one order by ID.
- Order lines synced via `sync_order_lines()` into `woo.order.line.sync`.

Status mapping:
- `_map_woo_status()` maps Woo states to local tracking:
  - `pending -> pending`
  - `processing/on-hold -> confirmed`
  - `completed -> delivered`
  - `cancelled -> cancelled`
  - `refunded -> refunded`
  - `failed -> cancelled`
  - default -> `draft`

Export logic:
- `woo.order.sync.action_push_to_woo()` updates order status, billing names/email, and customer note.

### Customer Sync
Import logic:
- From customer endpoint: `woo.instance.action_sync_customers()`.
- From order payload during order sync/webhook: `_sync_customer_from_order()`.
- Guest fallback customer IDs use `guest_<email>`.

Export logic:
- `woo.customer.sync.action_push_to_woo()` creates/updates Woo customer.
- Includes fallback update payload if Woo blocks email edits (`woocommerce_rest_cannot_edit` handling).

### Inventory Sync
Logic:
- `woo.instance.sync_inventory_from_woo()` pulls `/products`.
- Quantity rules:
  - If `manage_stock=True`: use `stock_quantity`.
  - Else: set quantity to `1` if status `instock`, otherwise `0`.
- Records stored in `woo.inventory`.

### Price Sync
Implemented price-related sync:
- Product regular/sale prices are read and written in `woo.product.sync`.
- Order totals are pulled into `woo.order.sync.total_amount`.
- No standalone dedicated price-only scheduler/mapping flow. **Needs confirmation**

## 8. Automation (Cron Jobs)
Defined cron jobs loaded by manifest:
1. `WooCommerce Auto Sync`
   - XML: `data/cron.xml`
   - Model/method: `woo.instance.cron_auto_sync()`
   - Frequency: every 15 minutes
   - Purpose: run entity syncs per instance based on auto flags and interval logic.
2. `Sync Woo Order Status`
   - XML: `data/woo_order_cron.xml`
   - Model/method: `woo.order.sync.cron_sync_woo_order_status()`
   - Frequency: every 5 minutes
   - Purpose: refresh status/details for existing synced orders.

Additional note:
- `views/woo_cron.xml` also defines an `ir_cron_woo_auto_sync` record but is not loaded in manifest. **Needs confirmation**

## 9. Monitoring & Logs
Where logs are stored:
- Structured sync logs:
  - `woo.report` (run-level record)
  - `woo.report.line` (detail line)
- Sync lock/state:
  - `woo.sync.status` (`last_sync`, `syncing`, `last_error`)
- Server logs:
  - Python `_logger` messages in webhook, dashboard, and services.

Error tracking:
- Failures create `woo.report` entries with `status='failed'` and error text.
- Webhook failures are logged via `woo.webhook.sync._log_webhook()`.
- AI service catches provider errors and returns fallback status/error message.

Retry mechanism:
- No explicit retry queue/backoff implementation found.
- Retry is operationally done by manual buttons or next cron run.

## 10. Menus & Screens
`WooCommerce` (root):
- Purpose: entry point, opens dashboard client action.

`WooCommerce > Instances`:
- Purpose: store-level connection and sync controls.
- Key fields: URL/keys, WP credentials, webhook secret, webhook flags, auto-sync flags/intervals.
- Actions/buttons: `Test Connection`, `Sync Products`, `Sync Orders`, `Sync Categories`, `Sync Coupons`, `Sync Inventory`, and kanban `Sync Analytics`.

`WooCommerce > Dashboard`:
- Purpose: opens JS dashboard action (`tag="woo_dashboard"`).
- Data source: `/woo/dashboard/data` -> `woo.dashboard.get_dashboard_data`.

`WooCommerce > WooCommerce Data > Products`:
- Purpose: product sync records.
- Key fields: product link, SKU, stock, prices, categories/tags, Woo ID, state, sync date.
- Actions: pull/push in list; in form pull, push, open in Woo, AI content actions.

`WooCommerce > WooCommerce Data > Customers`:
- Purpose: customer sync records.
- Key fields: name, email, phone, Woo customer ID, instance, state.
- Actions: create/update in Woo, pull from Woo, smart button to customer orders.

`WooCommerce > WooCommerce Data > Orders`:
- Purpose: order sync records and lines.
- Key fields: order number/ID, customer, amount, status, Woo status, sale order link.
- Actions: clean duplicates (list), add order, pull/push, create sale order.

`WooCommerce > WooCommerce Data > Categories`:
- Purpose: category sync records.
- Key fields: category IDs, slug, parent, count, description, state.
- Actions: create/update in Woo, pull from Woo, smart button to related Odoo products.

`WooCommerce > Coupons`:
- Purpose: coupon sync records.
- Key fields: code, discount type/amount, usage limits, expiry, Woo ID, instance.
- Actions: create/update in Woo, pull from Woo.

`WooCommerce > Field Mapping > Product/Customer/Category Field Mapping`:
- Purpose: map Woo payload keys to Odoo sync model fields.
- Key fields: instance, model, Odoo field, Woo field key, active.
- Actions: `Test Mapping`.

`WooCommerce > Inventory`:
- Purpose: inventory snapshot by Woo product.
- Key fields: product name, SKU, quantity, stock status.
- Actions: `Refresh Inventory`.

`WooCommerce > Shipping > Delivery Orders`:
- Purpose: list outgoing pickings (`stock.picking`).

`WooCommerce > Shipping > Woo Tracking`:
- Purpose: list completed outgoing pickings.

`WooCommerce > Reports`:
- `Sync Reports`: non-webhook sync log records.
- `Webhook Reports`: webhook-only records.
- `Sales Report`: graph/pivot/list on `woo.order.sync`.
- `Cancelled Orders`: filtered reporting action.
- `Mapping Reports`: opens mapping records.

## 11. Troubleshooting
| Issue | Cause | Solution |
|------|------|---------|
| Test connection fails | Missing `wp_username` or `application_password` | Fill WP credentials in instance and retry `Test Connection` |
| Unauthorized (401) while pulling data | Invalid keys, protocol mismatch, or permission issue | Verify `shop_url`, key permissions, and whether store requires HTTP/HTTPS normalization |
| Product push fails | Missing `woo_product_id` on record | Pull/import product first or ensure Woo ID is set |
| Order to Sale Order fails with SKU mapping error | `woo.order.line.sync.product_id` not resolved from SKU | Ensure `product.product.default_code` matches Woo SKU before creating sale order |
| Webhook ignored | Topic flags disabled or unmatched topic/instance | Enable relevant webhook flags; verify webhook source URL and instance resolution |
| Webhook signature invalid | Wrong `webhook_secret` or mismatched payload signature | Align Woo webhook secret with `woo.instance.webhook_secret` |
| Field mapping test fails | Sample payload fetch failed or key empty | Recheck credentials/URL, refresh Woo field catalog, test with a known non-empty Woo key |
| Auto sync appears idle | Auto flags disabled or no interval trigger yet | Enable entity auto flags and wait for cron interval or run manual sync |

## 12. FAQ
Q: Why did sync fail with a generic error?  
A: Check `WooCommerce > Reports > Sync Reports` for operation-level message and error details.

Q: Why are products not imported?  
A: Verify instance credentials, API access, and that Woo products exist. Then run `Sync Products` from the instance form.

Q: How do I reconnect Woo after credentials change?  
A: Update `consumer_key`, `consumer_secret` (and WP credentials if used), then run `Test Connection`.

Q: Do customers sync directly or through orders?  
A: Both paths exist. Customers can be fetched from `/customers`, and also created/updated from order billing payloads.

Q: How do webhook updates appear in Odoo?  
A: Configure Woo webhooks to `/woo/webhook`, optionally set `webhook_secret`, and enable relevant webhook flags per instance.

Q: Is there automatic order status refresh?  
A: Yes, cron `Sync Woo Order Status` runs every 5 minutes.

## 13. Best Practices
- Use one Woo instance record per store and keep credentials scoped correctly.
- Set and validate SKU strategy (`default_code`) before order-to-sale-order conversion.
- Configure field mappings only for fields that exist on target sync models.
- Enable webhook secret validation in production.
- Use reports menu to monitor failures before bulk re-runs.
- Start with manual sync for first run, then enable auto-sync flags incrementally.
- For AI features, configure API key/model first and validate fallback behavior in non-production data.

## 14. Appendix
Model names:
- `woo.instance`
- `woo.product.sync`
- `woo.customer.sync`
- `woo.order.sync`
- `woo.order.line.sync`
- `woo.category.sync`
- `woo.coupon.sync`
- `woo.inventory`
- `woo.field`
- `woo.field.mapping`
- `woo.report`
- `woo.report.line`
- `woo.sync.status`
- `woo.ai.insight`
- `woo.ai.content.wizard`
- `woo.dashboard` (abstract)
- `woo.webhook.sync` (abstract)
- `woo.connector` (legacy/simple)

Important methods:
- Instance/core:
  - `action_test_connection`, `action_sync_products`, `action_sync_orders`, `action_sync_customers`, `action_sync_categories`, `action_sync_coupons`, `sync_inventory_from_woo`, `cron_auto_sync`, `_create_sync_report`, `_apply_field_mapping`
- Product:
  - `action_pull_from_woo`, `action_push_to_woo`, `_prepare_vals`
- Order:
  - `sync_from_woocommerce`, `sync_order_lines`, `action_push_to_woo`, `action_create_sale_order`, `cron_sync_woo_order_status`
- Customer/category/coupon:
  - `action_push_to_woo`, `action_pull_from_woo`
- Webhook:
  - `sync_product`, `sync_customer`, `sync_order`, `sync_category`, `sync_coupon`
- AI:
  - `WooAIService.generate_sales_inventory_insights`, `WooAIService.generate_product_content`, wizard `action_generate_preview`, `action_apply_to_product`

HTTP/controller endpoints:
- Odoo endpoints:
  - `POST /woo/webhook`
  - `POST /woo/webhook/order`
  - JSON `/woo/dashboard/data`
  - JSON `POST /ai/chatbot/message`
- WooCommerce endpoints used by code:
  - `/wp-json/wc/v3/system_status`
  - `/wp-json/wc/v3/products`
  - `/wp-json/wc/v3/orders`
  - `/wp-json/wc/v3/customers`
  - `/wp-json/wc/v3/products/categories`
  - `/wp-json/wc/v3/coupons`
  - `/wp-json/wc/v3/reports/sales`
  - `/wp-json/wc-analytics/reports/revenue/stats`
  - `/wp-json/wc-analytics/reports/categories`
  - `/wp-json/wc-analytics/reports/products`
