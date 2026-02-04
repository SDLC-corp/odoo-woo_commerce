from odoo import http, fields
from odoo.http import request
import logging
import hmac
import hashlib
import base64
import json
from urllib.parse import urlparse

_logger = logging.getLogger(__name__)


class WooWebhookController(http.Controller):
    def _normalize_host(self, url):
        if not url:
            return ""
        try:
            parsed = urlparse(url)
            host = parsed.netloc or parsed.path
            return host.lower().strip().rstrip("/")
        except Exception:
            return (url or "").lower().strip().rstrip("/")

    @http.route(
        "/woo/webhook",
        type="http",
        auth="public",
        methods=["POST"],
        csrf=False,
    )
    def woo_webhook(self):
        raw = request.httprequest.data or b""
        payload = request.httprequest.get_json(silent=True) or {}
        if not payload and raw:
            try:
                payload = json.loads(raw.decode("utf-8"))
            except Exception:
                payload = {}

        topic = request.httprequest.headers.get("X-WC-Webhook-Topic")
        source = request.httprequest.headers.get("X-WC-Webhook-Source")
        signature = request.httprequest.headers.get("X-WC-Webhook-Signature")
        instance_id = request.params.get("instance_id") or request.params.get("instance")

        _logger.info("Woo webhook hit | topic=%s | source=%s", topic, source)

        Instance = request.env["woo.instance"].sudo()
        instance = False
        if instance_id:
            instance = Instance.search([("id", "=", int(instance_id))], limit=1)
        if not instance:
            domain = [("active", "=", True)]
            if source:
                source_host = self._normalize_host(source)
                domain = [
                    ("active", "=", True),
                    "|",
                    ("shop_url", "ilike", source_host),
                    ("shop_url", "ilike", source_host.replace("http://", "").replace("https://", "")),
                ]
            instance = Instance.search(domain, limit=1)
        if not instance and source:
            source_host = self._normalize_host(source)
            instance = Instance.search(
                [("active", "=", True), ("shop_url", "ilike", source_host)],
                limit=1,
            )
        if not instance and source:
            instance = Instance.search([("active", "=", True)], limit=1)

        if not instance:
            return request.make_response('{"status":"no_instance"}', headers=[("Content-Type", "application/json")])

        # Signature check (optional)
        if instance.webhook_secret and signature:
            computed = base64.b64encode(
                hmac.new(
                    instance.webhook_secret.encode("utf-8"),
                    raw,
                    hashlib.sha256,
                ).digest()
            ).decode("utf-8")
            if not hmac.compare_digest(computed, signature):
                _logger.warning("Woo webhook signature mismatch")
                request.env["woo.webhook.sync"].sudo()._log_webhook(
                    instance,
                    "Webhook Signature",
                    "failed",
                    "Invalid signature",
                    source_action="signature_invalid",
                )
                return request.make_response('{"status":"invalid_signature"}', headers=[("Content-Type", "application/json")])
        elif instance.webhook_secret and not signature:
            _logger.warning("Woo webhook missing signature header")
            request.env["woo.webhook.sync"].sudo()._log_webhook(
                instance,
                "Webhook Signature",
                "failed",
                "Missing signature header",
                source_action="signature_missing",
            )

        Sync = request.env["woo.webhook.sync"].sudo()

        if not topic:
            resource = payload.get("resource")
            event = payload.get("event")
            if resource and event:
                topic = f"{resource}.{event}"

        handled = False
        operation = "Webhook"
        if topic:
            if topic.startswith("product."):
                operation = "Webhook Product"
            elif topic.startswith("customer."):
                operation = "Webhook Customer"
            elif topic.startswith("order."):
                operation = "Webhook Order"
            elif "category" in topic:
                operation = "Webhook Category"
            elif topic.startswith("coupon."):
                operation = "Webhook Coupon"

        if topic and topic.startswith("product."):
            product_flags_enabled = not (instance.webhook_product_create or instance.webhook_product_update)
            if topic.endswith("created") and (instance.webhook_product_create or product_flags_enabled):
                Sync.sync_product(payload, instance, source_action="product_create")
                handled = True
            if topic.endswith("updated") and (instance.webhook_product_update or product_flags_enabled):
                Sync.sync_product(payload, instance, source_action="product_update")
                handled = True
        elif topic and topic.startswith("customer."):
            customer_flags_enabled = not (instance.webhook_customer_create or instance.webhook_customer_update)
            if topic.endswith("created") and (instance.webhook_customer_create or customer_flags_enabled):
                Sync.sync_customer(payload, instance, source_action="customer_create")
                handled = True
            if topic.endswith("updated") and (instance.webhook_customer_update or customer_flags_enabled):
                Sync.sync_customer(payload, instance, source_action="customer_update")
                handled = True
        elif topic and topic.startswith("order."):
            order_flags_enabled = not (instance.webhook_order_create or instance.webhook_order_update)
            if topic.endswith("created") and (instance.webhook_order_create or order_flags_enabled):
                Sync.sync_order(payload, instance, source_action="order_create")
                handled = True
            if topic.endswith("updated") and (instance.webhook_order_update or order_flags_enabled):
                Sync.sync_order(payload, instance, source_action="order_update")
                handled = True
        elif topic and ("category" in topic):
            category_flags_enabled = not (instance.webhook_category_create or instance.webhook_category_update)
            if topic.endswith("created") and (instance.webhook_category_create or category_flags_enabled):
                Sync.sync_category(payload, instance, source_action="category_create")
                handled = True
            if topic.endswith("updated") and (instance.webhook_category_update or category_flags_enabled):
                Sync.sync_category(payload, instance, source_action="category_update")
                handled = True
        elif topic and topic.startswith("coupon."):
            coupon_flags_enabled = not (instance.webhook_giftcard_create or instance.webhook_giftcard_update)
            if topic.endswith("created") and (instance.webhook_giftcard_create or coupon_flags_enabled):
                Sync.sync_coupon(payload, instance, source_action="coupon_create")
                handled = True
            if topic.endswith("updated") and (instance.webhook_giftcard_update or coupon_flags_enabled):
                Sync.sync_coupon(payload, instance, source_action="coupon_update")
                handled = True
        else:
            _logger.info("Unhandled Woo webhook topic: %s", topic)

        if not handled:
            Sync._log_webhook(
                instance,
                operation,
                "ignored",
                f"Webhook received but not processed (topic={topic})",
                source_action="ignored",
            )

        return request.make_response('{"status":"ok"}', headers=[("Content-Type", "application/json")])

    @http.route(
        "/woo/webhook/order",
        type="json",
        auth="public",
        methods=["POST"],
        csrf=False,
    )
    def woo_order_webhook(self, **payload):
        """
        Dynamic Woo Order Status Webhook
        """
        _logger.info("Woo Order Webhook: %s", payload)

        woo_order_id = payload.get("id")
        woo_status = payload.get("status")

        if not woo_order_id:
            return {"status": "ignored"}

        order = request.env["woo.order.sync"].sudo().search(
            [("woo_order_id", "=", str(woo_order_id))],
            limit=1,
        )

        if not order:
            return {"status": "order_not_found"}

        order.write({
            "woo_status": woo_status,
            "synced_on": fields.Datetime.now(),
        })

        _logger.info(
            "Order %s updated dynamically to Woo status: %s",
            woo_order_id,
            woo_status,
        )

        return {"status": "success"}
