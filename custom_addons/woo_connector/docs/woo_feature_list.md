# Woo Connector Feature List (Code Extracted)

## Core Integration
- Multi-store Woo instance model (`woo.instance`)
- Woo API client via `woocommerce.API` and direct `requests` fallbacks
- URL normalization and local-host SSL handling

## Product
- Bulk product pull from Woo to Odoo sync model
- Single product pull by Woo product ID
- Product push update to Woo
- Category/tag creation during import
- Product-template linking by SKU/default code
- Open product in Woo admin URL action

## Orders
- Bulk order pull from Woo
- Single order pull by Woo order ID
- Order line sync model with SKU/product mapping
- Push order status/billing note to Woo
- Convert synced Woo order into Odoo `sale.order`
- Duplicate cleanup (SQL + action-level cleanup)
- Scheduled status refresh cron

## Customers
- Pull customers from Woo customer endpoint
- Auto customer upsert from order billing payload
- Guest customer fallback key (`guest_<email>`)
- Push customer create/update to Woo with permission-safe fallback payload

## Categories
- Pull categories from Woo
- Push create/update category to Woo
- Product count smart button action to Odoo products

## Coupons
- Pull coupons from Woo
- Push create/update coupon to Woo
- Expiry date formatting and sync state tracking

## Inventory
- Inventory sync from Woo product stock to `woo.inventory`
- Quantity derivation for non-managed stock
- Inventory refresh action for one or multiple instances

## Mapping
- Generic field mapping model by entity (`product`, `order`, `customer`, `category`)
- Woo field catalog model (`woo.field`)
- Sample payload extraction for mapping
- Nested key extraction support (example `billing.email`)
- Mapping test button with live sample validation
- Protected core fields to prevent identity overwrite

## Webhooks
- Public webhook endpoint `/woo/webhook`
- Optional signature verification with HMAC SHA-256 + base64
- Topic-based sync routing:
  - `product.*`
  - `customer.*`
  - `order.*`
  - `category*`
  - `coupon.*`
- Order status webhook endpoint `/woo/webhook/order`

## Automation
- Cron: auto sync all enabled entities per instance (`cron_auto_sync`)
- Cron: Woo order status sync (`cron_sync_woo_order_status`)
- Per-entity auto flags and interval types (hours/days/weeks/months)

## Reporting and Monitoring
- Sync report header model (`woo.report`)
- Sync report line model (`woo.report.line`)
- Webhook/non-webhook report split via computed `has_webhook`
- Sync lock/status model (`woo.sync.status`)
- Dashboard refresh events via `bus.bus` broadcast

## Dashboard and Analytics
- Dashboard JSON endpoint `/woo/dashboard/data`
- Totals, payment breakdown, status breakdown, recent orders
- Woo analytics endpoint consumption for revenue/category/product stats
- Local fallback totals from sync tables

## AI and Assistant
- AI provider wrapper with OpenAI-compatible endpoint
- AI insights generation and storage (`woo.ai.insight`)
- AI product content generation wizard (`woo.ai.content.wizard`)
- Product AI actions:
  - Generate description
  - Generate short description
  - Improve SEO text
  - Suggest tags
- Intent chatbot endpoint `/ai/chatbot/message` with operational answers

## UI / Menus
- WooCommerce root app/menu
- Instances, Dashboard, Data submenus, Field Mapping submenus
- Inventory, Shipping, Reports menus
- Sales and order analytical report actions
