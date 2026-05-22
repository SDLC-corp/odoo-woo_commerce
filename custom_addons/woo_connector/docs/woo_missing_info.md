# Woo Connector Missing / Unclear Items

Items below are marked as **Needs confirmation** based on current code state.

## 1. Odoo Version Support
- Manifest does not explicitly pin supported Odoo major version.
- Repository path indicates Odoo 18.
- **Needs confirmation**: official supported versions.

## 2. Legacy Connector Model Usage
- `woo.connector` model and `connector_view.xml` exist.
- Manifest does not load `connector_view.xml`.
- **Needs confirmation**: whether `woo.connector` is still intended for use.

## 3. Duplicate/Overlapping XML Definitions
- `action_woo_instance` appears in both `views/woo_actions.xml` and `views/woo_instance_view.xml`.
- `action_woo_dashboard` appears in both `views/woo_actions.xml` and `views/woo_dashboard_action.xml`.
- `product.template` Woo form inherit is defined in both `product_template_woo_view.xml` and `woo_product_sync_view.xml` with same XML ID.
- **Needs confirmation**: intended final action/view ownership.

## 4. Unloaded XML Files
- `views/woo_cron.xml` defines a cron but is not listed in manifest data.
- `views/woo_dashboard_view.xml` is not listed in manifest and is not wrapped in `<odoo>...</odoo>`.
- **Needs confirmation**: whether these files are deprecated or should be loaded/fixed.

## 5. Auto Sync Time Selectors
- `auto_sync_hour`, `auto_sync_minute`, `auto_sync_weekday`, `auto_sync_month_day` are present in UI.
- `cron_auto_sync()` currently checks elapsed interval only (`_is_time_to_sync`) and does not use these selectors.
- **Needs confirmation**: whether exact clock-time scheduling is required.

## 6. Product Sync Action on `woo.product.sync`
- Method `woo.product.sync.action_sync_products()` references `m.woo_field` and `m.odoo_field`.
- Mapping model uses `woo_field_key` and `odoo_field_id`; referenced fields do not exist.
- **Needs confirmation**: method appears stale/unused or needs refactor.

## 7. Duplicate Method Definition
- `woo.product.sync.action_open_odoo_product()` is defined twice; second definition overrides first.
- Behavior now opens product form with defaults, not necessarily the linked `product_tmpl_id`.
- **Needs confirmation**: intended behavior.

## 8. Test Connection Credential Requirement
- `action_test_connection()` requires `wp_username` + `application_password`.
- Other sync paths primarily use consumer key/secret.
- **Needs confirmation**: whether test should support consumer key/secret-only mode.

## 9. Security Access Scope
- `security/ir.model.access.csv` has duplicate IDs/names and some rows with empty `group_id`.
- Empty `group_id` broadens access.
- **Needs confirmation**: target permission model and whether duplicates are intentional.

## 10. Coupon/Giftcard Naming
- Webhook flags are named `webhook_giftcard_create/update` but used for coupon webhook handling.
- Cron flag is `cron_sync_giftcards` while sync model is coupons.
- **Needs confirmation**: naming standard and whether gift card model is planned.

## 11. `product.brand` Dependency
- `woo.product.sync` includes `brand_id = Many2one('product.brand')`.
- Manifest dependencies do not include a module that clearly provides `product.brand`.
- **Needs confirmation**: dependency requirement for brand model.

## 12. Price Sync Scope
- Product regular/sale prices are synced with product pull/push.
- No dedicated price-only scheduler/action was found.
- **Needs confirmation**: whether separate price sync process is required.
