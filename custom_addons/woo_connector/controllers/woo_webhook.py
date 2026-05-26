from odoo import api, http, fields
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

    def _headers_to_dict(self):
        try:
            return dict(request.httprequest.headers.items())
        except Exception:
            return {}

    def _safe_create_webhook_log(self, vals):
        """Create a webhook log on a dedicated cursor.

        The log row is committed immediately and survives any rollback in the
        main request transaction so we never silently drop a webhook event.
        """
        try:
            registry = request.env.registry
            uid = request.env.uid or 1
            ctx = request.env.context
            with registry.cursor() as new_cr:
                new_env = api.Environment(new_cr, uid, ctx)
                log = new_env["woo.webhook.log"].sudo().create(vals)
                new_cr.commit()
                log_id = log.id
            return request.env["woo.webhook.log"].sudo().browse(log_id)
        except Exception as exc:
            _logger.warning("Unable to create webhook log on isolated cursor: %s", exc)
            try:
                return request.env["woo.webhook.log"].sudo().create(vals)
            except Exception as fallback_exc:
                _logger.exception("Webhook log creation failed: %s", fallback_exc)
                return False

    def _safe_update_webhook_log(self, webhook_log, vals):
        """Update a webhook log on a dedicated cursor so status survives rollbacks."""
        if not webhook_log:
            return
        log_id = getattr(webhook_log, "id", False)
        if not log_id:
            return
        try:
            registry = request.env.registry
            uid = request.env.uid or 1
            ctx = request.env.context
            with registry.cursor() as new_cr:
                new_env = api.Environment(new_cr, uid, ctx)
                rec = new_env["woo.webhook.log"].sudo().browse(log_id)
                if rec.exists():
                    rec.write(vals)
                    new_cr.commit()
        except Exception as exc:
            _logger.warning("Unable to update webhook log %s on isolated cursor: %s", log_id, exc)
            try:
                if webhook_log.exists():
                    webhook_log.sudo().write(vals)
            except Exception as fallback_exc:
                _logger.warning("Webhook log update fallback failed for %s: %s", log_id, fallback_exc)

    @http.route(
        "/woo/webhook/ping",
        type="http",
        auth="public",
        methods=["GET", "POST"],
        csrf=False,
    )
    def woo_webhook_ping(self, **kwargs):
        """Diagnostic endpoint that always creates a Webhook Log entry.

        Hit this from a browser or curl when you need to confirm the Odoo
        instance is reachable from the outside world and that the Webhook
        Logs page renders incoming events end-to-end.
        """
        headers_dict = self._headers_to_dict()
        instance = request.env["woo.instance"].sudo().search(
            [("active", "=", True)], order="id desc", limit=1
        )
        payload = {
            "source": "ping",
            "remote_addr": request.httprequest.remote_addr,
            "method": request.httprequest.method,
            "query": dict(kwargs),
            "_simulated": True,
        }
        vals = request.env["woo.webhook.log"].sudo().prepare_create_vals(
            instance=instance or False,
            topic="diagnostic.ping",
            payload=payload,
            headers=headers_dict,
            source_action="webhook_ping",
            status="success",
        )
        vals["processed_datetime"] = fields.Datetime.now()
        log = self._safe_create_webhook_log(vals)
        body = json.dumps({
            "status": "ok",
            "log_id": log.id if log else False,
            "instance_id": instance.id if instance else False,
            "message": "Open WooCommerce > Reporting > Webhook Logs to see this entry.",
        })
        return request.make_response(body, headers=[("Content-Type", "application/json")])

    @http.route(
        "/woo/webhook",
        type="http",
        auth="public",
        methods=["GET"],
        csrf=False,
    )
    def woo_webhook_get(self, **kwargs):
        """Return a diagnostic JSON when someone visits the URL with GET.

        WooCommerce delivers via POST. A GET here usually means a human
        verifying reachability — return a clear hint and *do not* log it as
        a webhook event (use /woo/webhook/ping if you want a row created).
        """
        body = json.dumps({
            "status": "ok",
            "message": (
                "Woo webhook endpoint is reachable. WooCommerce should POST "
                "to this URL with X-WC-Webhook-* headers. To log a diagnostic "
                "entry, GET /woo/webhook/ping instead."
            ),
            "method": "POST",
        })
        return request.make_response(body, headers=[("Content-Type", "application/json")])

    @http.route(
        "/woo/webhook",
        type="http",
        auth="public",
        methods=["POST"],
        csrf=False,
    )
    def woo_webhook(self, **kwargs):
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
        headers_dict = self._headers_to_dict()
        instance_id = (
            kwargs.get("instance_id")
            or kwargs.get("instance")
            or request.params.get("instance_id")
            or request.params.get("instance")
        )

        _logger.info("Woo webhook hit | topic=%s | source=%s", topic, source)

        WebhookLog = request.env["woo.webhook.log"].sudo()
        webhook_log = self._safe_create_webhook_log(
            WebhookLog.prepare_create_vals(
                instance=False,
                topic=topic,
                payload=payload,
                headers=headers_dict,
                source_action="webhook_received",
                status="received",
            )
        )

        Instance = request.env["woo.instance"].sudo()
        instance = False
        if instance_id:
            try:
                instance = Instance.search([("id", "=", int(instance_id))], limit=1)
            except (TypeError, ValueError):
                instance = False
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

        if webhook_log and instance:
            self._safe_update_webhook_log(webhook_log, {"instance_id": instance.id})

        if not instance:
            self._safe_update_webhook_log(
                webhook_log,
                {
                    "status": "ignored",
                    "error_message": "No matching active Woo instance found for webhook.",
                    "processed_datetime": fields.Datetime.now(),
                    "source_action": "ignored",
                },
            )
            return request.make_response('{"status":"no_instance"}', headers=[("Content-Type", "application/json")])

        Sync = request.env["woo.webhook.sync"].sudo().with_context(
            woo_webhook_log_id=webhook_log.id if webhook_log else False
        )

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
                report = Sync._log_webhook(
                    instance,
                    "Webhook Signature",
                    "failed",
                    "Invalid signature",
                    source_action="signature_invalid",
                    payload_data=payload,
                )
                self._safe_update_webhook_log(
                    webhook_log,
                    {
                        "status": "failed",
                        "signature_status": "invalid",
                        "error_message": "Invalid signature",
                        "processed_datetime": fields.Datetime.now(),
                        "source_action": "signature_invalid",
                        "related_report_id": report.id if report else False,
                    },
                )
                return request.make_response('{"status":"invalid_signature"}', headers=[("Content-Type", "application/json")])
        elif instance.webhook_secret and not signature:
            _logger.warning("Woo webhook missing signature header")
            report = Sync._log_webhook(
                instance,
                "Webhook Signature",
                "failed",
                "Missing signature header",
                source_action="signature_missing",
                payload_data=payload,
            )
            self._safe_update_webhook_log(
                webhook_log,
                {
                    "signature_status": "missing",
                    "source_action": "signature_missing",
                    "related_report_id": report.id if report else False,
                },
            )
        elif instance.webhook_secret and signature:
            self._safe_update_webhook_log(webhook_log, {"signature_status": "valid"})

        if not topic:
            resource = payload.get("resource")
            event = payload.get("event")
            if resource and event:
                topic = f"{resource}.{event}"

        handled = False
        handled_source_action = False
        handled_report = False
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

        try:
            if topic and topic.startswith("product."):
                product_flags_enabled = not (instance.webhook_product_create or instance.webhook_product_update)
                if topic.endswith("created") and (instance.webhook_product_create or product_flags_enabled):
                    handled_source_action = "product_create"
                    Sync.sync_product(payload, instance, source_action=handled_source_action)
                    handled = True
                if topic.endswith("updated") and (instance.webhook_product_update or product_flags_enabled):
                    handled_source_action = "product_update"
                    Sync.sync_product(payload, instance, source_action=handled_source_action)
                    handled = True
            elif topic and topic.startswith("customer."):
                customer_flags_enabled = not (instance.webhook_customer_create or instance.webhook_customer_update)
                if topic.endswith("created") and (instance.webhook_customer_create or customer_flags_enabled):
                    handled_source_action = "customer_create"
                    Sync.sync_customer(payload, instance, source_action=handled_source_action)
                    handled = True
                if topic.endswith("updated") and (instance.webhook_customer_update or customer_flags_enabled):
                    handled_source_action = "customer_update"
                    Sync.sync_customer(payload, instance, source_action=handled_source_action)
                    handled = True
            elif topic and topic.startswith("order."):
                order_flags_enabled = not (instance.webhook_order_create or instance.webhook_order_update)
                if topic.endswith("created") and (instance.webhook_order_create or order_flags_enabled):
                    handled_source_action = "order_create"
                    Sync.sync_order(payload, instance, source_action=handled_source_action)
                    handled = True
                if topic.endswith("updated") and (instance.webhook_order_update or order_flags_enabled):
                    handled_source_action = "order_update"
                    Sync.sync_order(payload, instance, source_action=handled_source_action)
                    handled = True
            elif topic and ("category" in topic):
                category_flags_enabled = not (instance.webhook_category_create or instance.webhook_category_update)
                if topic.endswith("created") and (instance.webhook_category_create or category_flags_enabled):
                    handled_source_action = "category_create"
                    Sync.sync_category(payload, instance, source_action=handled_source_action)
                    handled = True
                if topic.endswith("updated") and (instance.webhook_category_update or category_flags_enabled):
                    handled_source_action = "category_update"
                    Sync.sync_category(payload, instance, source_action=handled_source_action)
                    handled = True
            elif topic and topic.startswith("coupon."):
                coupon_flags_enabled = not (instance.webhook_giftcard_create or instance.webhook_giftcard_update)
                if topic.endswith("created") and (instance.webhook_giftcard_create or coupon_flags_enabled):
                    handled_source_action = "coupon_create"
                    Sync.sync_coupon(payload, instance, source_action=handled_source_action)
                    handled = True
                if topic.endswith("updated") and (instance.webhook_giftcard_update or coupon_flags_enabled):
                    handled_source_action = "coupon_update"
                    Sync.sync_coupon(payload, instance, source_action=handled_source_action)
                    handled = True
            else:
                _logger.info("Unhandled Woo webhook topic: %s", topic)
        except Exception as exc:
            self._safe_update_webhook_log(
                webhook_log,
                {
                    "status": "failed",
                    "error_message": str(exc),
                    "processed_datetime": fields.Datetime.now(),
                    "source_action": handled_source_action or "webhook_error",
                },
            )
            raise

        if not handled:
            handled_report = Sync._log_webhook(
                instance,
                operation,
                "ignored",
                f"Webhook received but not processed (topic={topic})",
                source_action="ignored",
                payload_data=payload,
            )
            self._safe_update_webhook_log(
                webhook_log,
                {
                    "status": "ignored",
                    "processed_datetime": fields.Datetime.now(),
                    "source_action": "ignored",
                    "error_message": f"Webhook received but not processed (topic={topic})",
                    "related_report_id": handled_report.id if handled_report else False,
                },
            )
        else:
            self._safe_update_webhook_log(
                webhook_log,
                {
                    "status": "success",
                    "processed_datetime": fields.Datetime.now(),
                    "source_action": handled_source_action or "webhook",
                },
            )

        return request.make_response('{"status":"ok"}', headers=[("Content-Type", "application/json")])

    @http.route(
        "/woo/webhook/order",
        type="http",
        auth="public",
        methods=["POST"],
        csrf=False,
    )
    def woo_order_webhook(self, **kwargs):
        """
        Dynamic Woo Order Status Webhook
        """
        payload = request.httprequest.get_json(silent=True) or {}
        headers_dict = self._headers_to_dict()
        if not payload and request.httprequest.data:
            try:
                payload = json.loads(request.httprequest.data.decode("utf-8"))
            except Exception:
                payload = {}
        if not payload:
            payload = kwargs

        _logger.info("Woo Order Webhook: %s", payload)

        WebhookLog = request.env["woo.webhook.log"].sudo()
        webhook_log = self._safe_create_webhook_log(
            WebhookLog.prepare_create_vals(
                instance=False,
                topic="order.status",
                payload=payload,
                headers=headers_dict,
                source_action="order_status_webhook_received",
                status="received",
            )
        )

        woo_order_id = payload.get("id")
        woo_status = payload.get("status")

        if not woo_order_id:
            self._safe_update_webhook_log(
                webhook_log,
                {
                    "status": "ignored",
                    "error_message": "Missing order id in payload.",
                    "processed_datetime": fields.Datetime.now(),
                    "source_action": "ignored",
                },
            )
            return request.make_response('{"status":"ignored"}', headers=[("Content-Type", "application/json")])

        order = request.env["woo.order.sync"].sudo().search(
            [("woo_order_id", "=", str(woo_order_id))],
            limit=1,
        )

        if not order:
            self._safe_update_webhook_log(
                webhook_log,
                {
                    "status": "ignored",
                    "woo_id": str(woo_order_id),
                    "error_message": "Order not found in woo.order.sync.",
                    "processed_datetime": fields.Datetime.now(),
                    "source_action": "order_status_not_found",
                },
            )
            return request.make_response('{"status":"order_not_found"}', headers=[("Content-Type", "application/json")])

        order.write({
            "woo_status": woo_status,
            "synced_on": fields.Datetime.now(),
        })

        if webhook_log:
            self._safe_update_webhook_log(
                webhook_log,
                {
                    "instance_id": order.instance_id.id if order.instance_id else False,
                    "woo_id": str(woo_order_id),
                    "status": "success",
                    "processed_datetime": fields.Datetime.now(),
                    "source_action": "order_status_update",
                },
            )

        _logger.info(
            "Order %s updated dynamically to Woo status: %s",
            woo_order_id,
            woo_status,
        )

        return request.make_response('{"status":"success"}', headers=[("Content-Type", "application/json")])
