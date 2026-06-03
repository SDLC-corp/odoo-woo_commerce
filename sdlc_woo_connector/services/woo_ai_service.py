import json
import logging
from collections import Counter

from odoo import fields

from .woo_ai_provider import (
    WooAIProvider,
    WooAIProviderDisabled,
    WooAIProviderError,
)


_logger = logging.getLogger(__name__)


class WooAIService:
    """Application service for AI insights and product-content generation."""

    def __init__(self, env):
        self.env = env
        self.provider = WooAIProvider(env)
        self.params = env["ir.config_parameter"].sudo()

    def _strip_code_fences(self, text):
        text = (text or "").strip()
        if text.startswith("```"):
            lines = text.splitlines()
            if lines and lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].startswith("```"):
                lines = lines[:-1]
            text = "\n".join(lines).strip()
        return text

    def _safe_json_loads(self, raw_text):
        cleaned = self._strip_code_fences(raw_text)
        return json.loads(cleaned) if cleaned else {}

    def _get_prompt_template(self, key, default):
        return self.params.get_param(key) or default

    def _format_currency(self, amount):
        return "%.2f" % float(amount or 0.0)

    def _fallback_insights(self, metrics):
        sales_7 = metrics.get("sales_last_7_days", {})
        sales_30 = metrics.get("sales_last_30_days", {})
        top_products = metrics.get("top_selling_products", [])[:3]
        low_stock = metrics.get("products_at_risk_of_stockout", [])[:3]
        slow = metrics.get("low_sales_products", [])[:3]

        revenue_trend = sales_30.get("revenue_change_pct", 0.0)
        order_trend = sales_30.get("order_change_pct", 0.0)

        summary_parts = [
            "Last 7 days revenue was %s from %s orders."
            % (
                self._format_currency(sales_7.get("revenue")),
                int(sales_7.get("orders", 0)),
            ),
            "Last 30 days revenue was %s with a %.1f%% revenue trend versus the previous 30 days."
            % (
                self._format_currency(sales_30.get("revenue")),
                revenue_trend,
            ),
        ]
        if top_products:
            summary_parts.append(
                "Top sellers are %s."
                % ", ".join(product["name"] for product in top_products)
            )
        if low_stock:
            summary_parts.append(
                "%s items have near-term stock risk."
                % len(metrics.get("products_at_risk_of_stockout", []))
            )

        recommendations = []
        for item in low_stock:
            recommendations.append(
                "Restock %s within %s days based on recent order velocity."
                % (item["name"], max(int(item.get("days_to_stockout", 0)), 1))
            )
        for item in slow:
            recommendations.append(
                "Review pricing or promotion for %s because it sold only %s units in the last 30 days."
                % (item["name"], item.get("units_sold_30_days", 0))
            )
        if not recommendations:
            recommendations.append(
                "No urgent stock issues were detected. Focus on maintaining sales momentum for top sellers."
            )

        return {
            "summary": " ".join(summary_parts),
            "predicted_top_products_to_restock": metrics.get("predicted_top_products_to_restock", []),
            "products_at_risk_of_stockout": metrics.get("products_at_risk_of_stockout", []),
            "low_sales_products": metrics.get("low_sales_products", []),
            "sales_summary": {
                "last_7_days": sales_7,
                "last_30_days": sales_30,
            },
            "repeat_customers": metrics.get("repeat_customers", []),
            "actionable_recommendations": recommendations[:6],
            "trend_snapshot": {
                "revenue_change_pct": revenue_trend,
                "order_change_pct": order_trend,
            },
        }

    def generate_sales_inventory_insights(self, metrics, context_meta):
        fallback = self._fallback_insights(metrics)
        system_prompt = self._get_prompt_template(
            "woocommerce_ai.prompt.insights",
            (
                "You are an ecommerce operations analyst. Return valid JSON only with keys: "
                "summary, predicted_top_products_to_restock, products_at_risk_of_stockout, "
                "low_sales_products, sales_summary, repeat_customers, actionable_recommendations."
            ),
        )
        user_prompt = json.dumps(
            {
                "context": context_meta,
                "metrics": metrics,
                "fallback_reference": fallback,
            },
            indent=2,
            default=str,
        )

        status = "fallback"
        error_message = False
        result = fallback

        try:
            raw = self.provider.generate_json(system_prompt, user_prompt, temperature=0.1)
            parsed = self._safe_json_loads(raw)
            if isinstance(parsed, dict):
                result = {
                    "summary": parsed.get("summary") or fallback["summary"],
                    "predicted_top_products_to_restock": parsed.get(
                        "predicted_top_products_to_restock"
                    ) or fallback["predicted_top_products_to_restock"],
                    "products_at_risk_of_stockout": parsed.get(
                        "products_at_risk_of_stockout"
                    ) or fallback["products_at_risk_of_stockout"],
                    "low_sales_products": parsed.get("low_sales_products")
                    or fallback["low_sales_products"],
                    "sales_summary": parsed.get("sales_summary") or fallback["sales_summary"],
                    "repeat_customers": parsed.get("repeat_customers")
                    or fallback["repeat_customers"],
                    "actionable_recommendations": parsed.get("actionable_recommendations")
                    or fallback["actionable_recommendations"],
                    "trend_snapshot": fallback["trend_snapshot"],
                }
                status = "success"
        except (WooAIProviderDisabled, WooAIProviderError, ValueError, TypeError) as exc:
            error_message = str(exc)
            _logger.warning("AI insights fallback triggered: %s", exc)

        return {
            "status": status,
            "error_message": error_message,
            "generated_at": fields.Datetime.now(),
            "summary_text": result["summary"],
            "insight_payload": result,
        }

    def _fallback_tags(self, product_payload):
        parts = [
            product_payload.get("name"),
            product_payload.get("category_name"),
            product_payload.get("sku"),
        ]
        raw_tokens = []
        for part in parts:
            if not part:
                continue
            raw_tokens.extend(str(part).replace("/", " ").replace("-", " ").split())
        tokens = [
            token.strip(",. ").lower()
            for token in raw_tokens
            if token and len(token.strip(",. ")) > 2
        ]
        unique = list(dict.fromkeys(tokens))
        return ", ".join(unique[:8])

    def _fallback_product_content(self, product_payload, options):
        tone = options.get("tone", "professional")
        seo_mode = options.get("seo_mode", False)
        name = product_payload.get("name") or "This product"
        category = product_payload.get("category_name") or "general merchandise"
        price = product_payload.get("price_label") or "available on request"
        sku = product_payload.get("sku") or "N/A"
        attributes = ", ".join(product_payload.get("attributes", [])) or "standard specifications"
        tags = self._fallback_tags(product_payload)

        long_description = (
            "<p><strong>%s</strong> is a %s offering crafted for customers who value %s. "
            "Priced at %s, it fits naturally into the %s range and supports clear catalogue merchandising.</p>"
            "<p>Key product references include SKU %s and attributes such as %s. "
            "Use this copy as a clean baseline and refine it for brand tone as needed.</p>"
        ) % (name, tone, attributes, price, category, sku, attributes)

        short_description = (
            "%s is a %s %s option with %s. SKU: %s."
        ) % (name, tone, category, attributes, sku)

        seo_title = "%s | %s" % (name, category.title())
        seo_description = (
            "Shop %s in %s. Discover %s at %s. SKU %s."
        ) % (name, category, attributes, price, sku)
        if seo_mode:
            seo_description += " Optimized for clear search-friendly product discovery."

        return {
            "generated_long_description": long_description,
            "generated_short_description": short_description,
            "generated_seo_title": seo_title[:70],
            "generated_seo_description": seo_description[:160],
            "generated_tags_text": tags,
        }

    def generate_product_content(self, product_payload, options):
        fallback = self._fallback_product_content(product_payload, options)
        system_prompt = self._get_prompt_template(
            "woocommerce_ai.prompt.product_content",
            (
                "You are an ecommerce copywriter. Return valid JSON only with keys: "
                "generated_long_description, generated_short_description, "
                "generated_seo_title, generated_seo_description, generated_tags_text."
            ),
        )
        user_prompt = json.dumps(
            {
                "product": product_payload,
                "options": options,
                "fallback_reference": fallback,
            },
            indent=2,
            default=str,
        )

        status = "fallback"
        error_message = False
        result = fallback

        try:
            raw = self.provider.generate_json(system_prompt, user_prompt, temperature=0.4)
            parsed = self._safe_json_loads(raw)
            if isinstance(parsed, dict):
                result = {
                    "generated_long_description": parsed.get("generated_long_description")
                    or fallback["generated_long_description"],
                    "generated_short_description": parsed.get("generated_short_description")
                    or fallback["generated_short_description"],
                    "generated_seo_title": parsed.get("generated_seo_title")
                    or fallback["generated_seo_title"],
                    "generated_seo_description": parsed.get("generated_seo_description")
                    or fallback["generated_seo_description"],
                    "generated_tags_text": parsed.get("generated_tags_text")
                    or fallback["generated_tags_text"],
                }
                status = "success"
        except (WooAIProviderDisabled, WooAIProviderError, ValueError, TypeError) as exc:
            error_message = str(exc)
            _logger.warning("AI product content fallback triggered: %s", exc)

        return {
            "status": status,
            "error_message": error_message,
            "generated_at": fields.Datetime.now(),
            **result,
        }

    def build_top_seller_restock_candidates(self, top_products, low_stock_map):
        candidates = []
        for product in top_products:
            sku = product.get("sku")
            low_stock = low_stock_map.get(sku) or {}
            candidates.append(
                {
                    "name": product.get("name"),
                    "sku": sku,
                    "units_sold_30_days": product.get("units_sold_30_days", 0),
                    "current_stock": low_stock.get("current_stock", 0.0),
                }
            )
        return candidates[:5]

    def build_repeat_customers(self, order_records):
        grouped = {}
        for order in order_records:
            email = (order.customer_email or "").strip().lower()
            if not email:
                continue
            grouped.setdefault(
                email,
                {
                    "email": email,
                    "customer_name": order.customer_name or email,
                    "order_count": 0,
                    "total_spent": 0.0,
                },
            )
            grouped[email]["order_count"] += 1
            grouped[email]["total_spent"] += float(order.total_amount or 0.0)

        customers = [
            values for values in grouped.values() if values["order_count"] > 1
        ]
        customers.sort(key=lambda item: (-item["order_count"], -item["total_spent"]))
        return customers[:5]

    def summarize_tags(self, tags_text):
        tags = [
            tag.strip()
            for tag in (tags_text or "").replace("\n", ",").split(",")
            if tag.strip()
        ]
        counts = Counter(tags)
        return list(counts.keys())
