# WooCommerce Connector AI Features

## Implemented Features

1. AI Sales & Inventory Insights
2. AI Product Content Assistant

## Configuration

Configure these system parameters from `Settings > Technical > System Parameters` or from `Settings` after enabling developer mode:

- `woocommerce_ai.enabled`
- `woocommerce_ai.provider`
- `woocommerce_ai.api_key`
- `woocommerce_ai.model`
- `woocommerce_ai.max_tokens`
- `woocommerce_ai.endpoint` (optional, for OpenAI-compatible providers)

## AI Insights

- Open `WooCommerce > Dashboard`
- Click `Generate AI Insights`
- The dashboard stores the latest insight text, JSON payload, generated time, and status
- If the external provider is unavailable, the connector stores a deterministic fallback summary instead of failing the dashboard

Example prompt intent:
- Summarize last 7/30 day sales
- Highlight stockout risk
- Identify slow-moving products
- Recommend restock actions

## AI Product Content Assistant

- Open `WooCommerce > WooCommerce Data > Products`
- Open a product
- Use one of these buttons:
  - `Generate Description`
  - `Generate Short Description`
  - `Improve SEO Text`
  - `Suggest Tags`
- Review the generated preview in the wizard
- Click `Apply to Product` to persist the chosen content

Example prompt intent:
- Generate product long description from name, category, SKU, attributes, and price
- Generate short ecommerce summary
- Improve SEO title/meta description
- Suggest tag keywords for catalog classification

## Notes

- The provider wrapper is isolated in `services/woo_ai_provider.py`
- Business/fallback orchestration lives in `services/woo_ai_service.py`
- The connector keeps working if AI is disabled or the provider call fails
