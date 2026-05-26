from odoo import models, fields, api, _
from odoo.exceptions import UserError
import requests
import json
from requests.exceptions import RequestException, Timeout
try:
    from woocommerce import API as WooAPI
except Exception:
    WooAPI = False
from datetime import datetime, timedelta
from dateutil.relativedelta import relativedelta
import logging
from datetime import datetime
from urllib.parse import urlparse
from time import perf_counter
import re

_logger = logging.getLogger(__name__)


class _FallbackWooAPI:
    """Requests-based fallback when python-woocommerce is not installed."""

    def __init__(self, instance):
        self.instance = instance

    def _build_url(self, endpoint):
        base_url = self.instance._get_base_url().rstrip("/")
        endpoint = (endpoint or "").lstrip("/")
        return f"{base_url}/wp-json/wc/v3/{endpoint}"

    def _request(self, method, endpoint, data=None, params=None):
        url = self._build_url(endpoint)
        verify_ssl = not self.instance._is_local_url(url)
        params = dict(params or {})

        auth_candidates = []
        if self.instance.consumer_key and self.instance.consumer_secret:
            auth_candidates.append((self.instance.consumer_key, self.instance.consumer_secret))
        if self.instance.wp_username and self.instance.application_password:
            auth_candidates.append((self.instance.wp_username, self.instance.application_password))

        seen = set()
        for auth in auth_candidates:
            if auth in seen:
                continue
            seen.add(auth)
            response = requests.request(
                method,
                url,
                auth=auth,
                params=params,
                json=data,
                timeout=30,
                verify=verify_ssl,
            )
            if response.status_code != 401:
                return response

        query_params = dict(params)
        if self.instance.consumer_key and self.instance.consumer_secret:
            query_params.update({
                "consumer_key": self.instance.consumer_key,
                "consumer_secret": self.instance.consumer_secret,
            })
        return requests.request(
            method,
            url,
            params=query_params,
            json=data,
            timeout=30,
            verify=verify_ssl,
        )

    def get(self, endpoint, params=None):
        return self._request("GET", endpoint, params=params)

    def post(self, endpoint, data=None):
        return self._request("POST", endpoint, data=data)

    def put(self, endpoint, data=None):
        return self._request("PUT", endpoint, data=data)

    def delete(self, endpoint, params=None):
        return self._request("DELETE", endpoint, params=params)


class WooInstance(models.Model):
    _name = "woo.instance"
    _description = "WooCommerce Instance"

    # ------------------------------------------------
    # BASIC CONFIG
    # ------------------------------------------------
    name = fields.Char(required=True, help="Display name for this WooCommerce instance (e.g. 'Main Store').")

    shop_url = fields.Char(
        string="Shop URL",
        required=True,
        help="Public base URL of the WooCommerce store (e.g. https://shop.example.com).",
    )
    consumer_key = fields.Char(
        required=True,
        help="WooCommerce REST API consumer key generated in WooCommerce > Settings > Advanced > REST API.",
    )
    consumer_secret = fields.Char(
        required=True,
        help="WooCommerce REST API consumer secret paired with the consumer key.",
    )
    active = fields.Boolean(
        default=True,
        help="Uncheck to disable this instance without deleting it. Inactive instances are excluded from cron sync and webhook routing.",
    )
    wp_username = fields.Char(
        string="WP Username",
        help="WordPress admin username, used as a fallback for endpoints not covered by the REST consumer key.",
    )
    application_password = fields.Char(
        string="Application Password",
        help="WordPress Application Password for the above user. Used when consumer key auth is rejected.",
    )
    webhook_secret = fields.Char(
        string="Webhook Secret",
        help="Shared secret used to verify HMAC signatures of incoming WooCommerce webhooks.",
    )
    smart_sku_matching = fields.Boolean(
        string="Enable Smart SKU Matching",
        default=True,
    )
    strict_sku_matching = fields.Boolean(
        string="Strict SKU Matching",
        default=True,
    )
    auto_mapping_creation = fields.Boolean(
        string="Enable Auto Mapping Creation",
        default=True,
    )
    strict_auto_mapping = fields.Boolean(
        string="Strict Auto Mapping",
        default=True,
    )
    auto_create_category_mapping = fields.Boolean(
        string="Auto Create Category Mapping",
        default=True,
    )
    auto_create_tag_mapping = fields.Boolean(
        string="Auto Create Tag Mapping",
        default=True,
    )
    ai_error_assistant_enabled = fields.Boolean(
        string="Enable AI Error Assistant",
        default=False,
    )
    ai_error_provider = fields.Selection(
        [
            ("openai", "OpenAI"),
            ("azure_openai", "Azure OpenAI"),
            ("custom", "Custom Endpoint"),
        ],
        string="AI Provider",
        default="openai",
    )
    ai_error_api_key = fields.Char(string="AI API Key")
    ai_error_model = fields.Char(string="AI Model", default="gpt-4o-mini")
    ai_error_endpoint = fields.Char(string="AI Endpoint URL", default="https://api.openai.com/v1")
    ai_error_api_version = fields.Char(string="Azure API Version", default="2024-02-15-preview")
    ai_error_max_tokens = fields.Integer(string="AI Max Tokens", default=500)
    ai_error_temperature = fields.Float(string="AI Temperature", default=0.2)
    ai_error_timeout_seconds = fields.Integer(string="AI Timeout (seconds)", default=20)

    # ------------------------------------------------
    # CONNECTION HEALTH
    # ------------------------------------------------
    health_last_checked_at = fields.Datetime(string="Last Health Check", readonly=True)
    health_overall_status = fields.Selection(
        [
            ("healthy", "Healthy"),
            ("warning", "Warning"),
            ("failed", "Failed"),
        ],
        string="Health Status",
        default="warning",
        readonly=True,
    )
    health_response_time_ms = fields.Float(string="API Response Time (ms)", readonly=True)
    health_woo_version = fields.Char(string="WooCommerce Version", readonly=True)
    health_currency = fields.Char(string="Woo Currency", readonly=True)
    health_last_error = fields.Text(string="Health Check Last Error", readonly=True)
    health_log_ids = fields.One2many(
        "woo.connection.health.log",
        "instance_id",
        string="Health Check Logs",
        readonly=True,
    )

    # ------------------------------------------------
    # ANALYTICS SNAPSHOT (PER INSTANCE)
    # ------------------------------------------------
    total_products = fields.Integer(string="Total Products", default=0)
    total_orders = fields.Integer(string="Total Orders", default=0)
    total_customers = fields.Integer(string="Total Customers", default=0)
    total_revenue = fields.Float(string="Total Revenue", default=0.0)
    last_sync = fields.Datetime(string="Last Sync")

    # ------------------------------------------------
    # WEBHOOK AUTO SYNC FLAGS
    # ------------------------------------------------
    webhook_product_create = fields.Boolean()
    webhook_product_update = fields.Boolean()
    webhook_customer_create = fields.Boolean()
    webhook_customer_update = fields.Boolean()
    webhook_order_create = fields.Boolean()
    webhook_order_update = fields.Boolean()
    webhook_category_create = fields.Boolean()
    webhook_category_update = fields.Boolean()
    webhook_giftcard_create = fields.Boolean()
    webhook_giftcard_update = fields.Boolean()

    # ------------------------------------------------
    # CRON FLAGS
    # ------------------------------------------------
    cron_sync_products = fields.Boolean()
    cron_sync_customers = fields.Boolean()
    cron_sync_orders = fields.Boolean()
    cron_sync_categories = fields.Boolean()
    cron_sync_giftcards = fields.Boolean()

    # ------------------------------------------------
    # AUTO SYNC CONFIG (SHOPIFY-LIKE)
    # ------------------------------------------------
    INTERVAL_TYPE = [
        ("hours", "Hourly"),
        ("days", "Daily"),
        ("weeks", "Weekly"),
        ("months", "Monthly"),
    ]

    auto_product_sync = fields.Boolean("Auto Product Sync")
    auto_product_interval_type = fields.Selection(INTERVAL_TYPE, default="hours")
    last_product_sync_at = fields.Datetime()

    auto_customer_sync = fields.Boolean("Auto Customer Sync")
    auto_customer_interval_type = fields.Selection(INTERVAL_TYPE, default="hours")
    last_customer_sync_at = fields.Datetime()

    auto_order_sync = fields.Boolean("Auto Order Sync")
    auto_order_interval_type = fields.Selection(INTERVAL_TYPE, default="hours")
    last_order_sync_at = fields.Datetime()

    auto_category_sync = fields.Boolean("Auto Category Sync")
    auto_category_interval_type = fields.Selection(INTERVAL_TYPE, default="days")
    last_category_sync_at = fields.Datetime()

    auto_coupon_sync = fields.Boolean("Auto Coupon Sync")
    auto_coupon_interval_type = fields.Selection(INTERVAL_TYPE, default="days")
    last_coupon_sync_at = fields.Datetime()

    auto_sync_hour = fields.Selection(
        [(str(i), f"{i:02d}") for i in range(0, 24)], string="Hour", default="0"
    )
    auto_sync_minute = fields.Selection(
        [(str(i), f"{i:02d}") for i in range(0, 60, 5)], string="Minute", default="0"
    )
    auto_sync_weekday = fields.Selection(
        [
            ("0", "Monday"),
            ("1", "Tuesday"),
            ("2", "Wednesday"),
            ("3", "Thursday"),
            ("4", "Friday"),
            ("5", "Saturday"),
            ("6", "Sunday"),
        ],
        string="Weekday",
        default="0",
    )
    auto_sync_month_day = fields.Selection(
        [(str(i), str(i)) for i in range(1, 32)], string="Day of Month", default="1"
    )

    @staticmethod
    def _normalize_shop_url_value(url):
        if not url:
            return url

        url = url.strip().rstrip("/")
        if not url:
            return url

        if not url.startswith(("http://", "https://")):
            if "localhost" in url or "127.0.0.1" in url:
                url = "http://" + url.lstrip("/")
            else:
                url = "https://" + url.lstrip("/")
        elif url.startswith("https://") and ("localhost" in url or "127.0.0.1" in url):
            url = url.replace("https://", "http://", 1)

        return url

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get("shop_url"):
                vals["shop_url"] = self._normalize_shop_url_value(vals["shop_url"])
        return super().create(vals_list)

    def write(self, vals):
        if vals.get("shop_url"):
            vals["shop_url"] = self._normalize_shop_url_value(vals["shop_url"])
        return super().write(vals)

    # =================================================
    # INTERNAL HELPERS
    # =================================================
    def _get_wcapi(self, rec):
        if not WooAPI:
            _logger.warning(
                "python-woocommerce package not installed; using requests-based fallback API for instance %s.",
                rec.display_name,
            )
            return _FallbackWooAPI(rec)
        return WooAPI(
            url=rec._get_base_url(),
            consumer_key=rec.consumer_key,
            consumer_secret=rec.consumer_secret,
            version="wc/v3",
            timeout=30,
        )

    def _parse_woo_datetime(self, value):
        if not value:
            return False
        try:
            clean = value.replace("Z", "+00:00")
            parsed = datetime.fromisoformat(clean)
            return parsed.replace(tzinfo=None)
        except Exception:
            try:
                return datetime.strptime(
                    value.replace("T", " "), "%Y-%m-%d %H:%M:%S"
                )
            except Exception:
                return False

    def _is_local_url(self, url):
        return "localhost" in (url or "") or "127.0.0.1" in (url or "")

    def _test_connection_base_candidates(self):
        """Build candidate base URLs for connection test.
        For localhost without explicit port, also try common local WP ports.
        """
        self.ensure_one()
        base_url = self._get_base_url()
        candidates = [base_url]

        parsed = urlparse(base_url)
        host = (parsed.hostname or "").lower()
        if host in ("localhost", "127.0.0.1") and parsed.port in (None, 80, 443):
            path = (parsed.path or "").rstrip("/")
            for port in (8080, 8000, 8888, 8081):
                candidate = f"{parsed.scheme}://{host}:{port}{path}"
                if candidate not in candidates:
                    candidates.append(candidate)

        return candidates

    def _woo_get(self, url, params=None, timeout=30):
        params = params or {}
        verify_ssl = not self._is_local_url(url)

        # 1) API consumer key/secret via basic auth.
        response = requests.get(
            url,
            auth=(self.consumer_key, self.consumer_secret),
            params=params,
            timeout=timeout,
            verify=verify_ssl,
        )

        # 2) Fallback with WP username + application password (if configured).
        if response.status_code == 401 and self.wp_username and self.application_password:
            response = requests.get(
                url,
                auth=(self.wp_username, self.application_password),
                params=params,
                timeout=timeout,
                verify=verify_ssl,
            )

        # 3) Fallback with consumer key/secret in query string (some local stacks require this).
        if response.status_code == 401:
            query = dict(params)
            query.update({
                "consumer_key": self.consumer_key,
                "consumer_secret": self.consumer_secret,
            })
            response = requests.get(
                url,
                params=query,
                timeout=timeout,
                verify=verify_ssl,
            )
        return response

    def _woo_options(self, url, params=None, timeout=20):
        params = params or {}
        verify_ssl = not self._is_local_url(url)

        response = requests.options(
            url,
            auth=(self.consumer_key, self.consumer_secret),
            params=params,
            timeout=timeout,
            verify=verify_ssl,
        )

        if response.status_code == 401 and self.wp_username and self.application_password:
            response = requests.options(
                url,
                auth=(self.wp_username, self.application_password),
                params=params,
                timeout=timeout,
                verify=verify_ssl,
            )

        if response.status_code == 401:
            query = dict(params)
            query.update({
                "consumer_key": self.consumer_key,
                "consumer_secret": self.consumer_secret,
            })
            response = requests.options(
                url,
                params=query,
                timeout=timeout,
                verify=verify_ssl,
            )
        return response

    def _normalize_sku(self, sku):
        value = (sku or "").strip()
        return value or False

    def _find_odoo_product_by_sku(self, sku, instance=None):
        self.ensure_one()
        normalized_sku = self._normalize_sku(sku)
        if not normalized_sku:
            return {"product_tmpl": False, "matched_by": False, "warning": False}

        strict = bool(self.strict_sku_matching)
        instance = instance or self
        ProductTmpl = self.env["product.template"].sudo()
        ProductVariant = self.env["product.product"].sudo()

        tmpl_domain = [("default_code", "=", normalized_sku)]
        if "woo_instance_id" in ProductTmpl._fields and instance:
            tmpl_domain.append(("woo_instance_id", "in", [False, instance.id]))
        tmpl_matches = ProductTmpl.search(tmpl_domain, order="id asc")
        if len(tmpl_matches) > 1:
            message = _(
                "Duplicate Odoo products found for SKU '%s'. Please resolve duplicate Internal References."
            ) % normalized_sku
            if strict:
                raise UserError(message)
            _logger.warning(message)
            return {"product_tmpl": tmpl_matches[:1], "matched_by": "sku_template", "warning": message}
        if tmpl_matches:
            return {"product_tmpl": tmpl_matches[:1], "matched_by": "sku_template", "warning": False}

        variant_domain = [("default_code", "=", normalized_sku)]
        if "woo_instance_id" in ProductTmpl._fields and instance:
            variant_domain.append(("product_tmpl_id.woo_instance_id", "in", [False, instance.id]))
        variant_matches = ProductVariant.search(variant_domain, order="id asc")
        if len(variant_matches) > 1:
            message = _(
                "Duplicate Odoo variants found for SKU '%s'. Please resolve duplicate Internal References."
            ) % normalized_sku
            if strict:
                raise UserError(message)
            _logger.warning(message)
            variant_matches = variant_matches[:1]

        if not variant_matches:
            return {"product_tmpl": False, "matched_by": False, "warning": False}

        variant = variant_matches[:1]
        template = variant.product_tmpl_id
        if template.product_variant_count > 1:
            message = _(
                "SKU '%s' belongs to a product variant in a multi-variant template. "
                "Unsafe overwrite avoided; manual review required."
            ) % normalized_sku
            _logger.warning(message)
            return {"product_tmpl": False, "matched_by": False, "warning": message}

        return {"product_tmpl": template, "matched_by": "sku_variant", "warning": False}

    def _find_woo_product_by_sku(self, sku):
        self.ensure_one()
        normalized_sku = self._normalize_sku(sku)
        if not normalized_sku:
            return {"product": False, "warning": False}

        wcapi = self._get_wcapi(self)
        response = wcapi.get("products", params={"sku": normalized_sku, "per_page": 20})
        if response.status_code != 200:
            raise UserError(
                _("Failed Woo SKU search for '%(sku)s'. Status: %(status)s\n%(body)s")
                % {
                    "sku": normalized_sku,
                    "status": response.status_code,
                    "body": response.text,
                }
            )

        found = response.json()
        if not isinstance(found, list) or not found:
            return {"product": False, "warning": False}

        strict = bool(self.strict_sku_matching)
        if len(found) > 1:
            message = _(
                "Multiple WooCommerce products found for SKU '%s'."
            ) % normalized_sku
            if strict:
                raise UserError(message)
            _logger.warning("%s Using first result due to non-strict mode.", message)

        candidate = found[0]
        candidate_type = (candidate.get("type") or "").lower()
        parent_id = int(candidate.get("parent_id") or 0)
        if candidate_type == "variation" or parent_id:
            message = _(
                "Woo SKU '%s' matched a variation record. Unsafe overwrite avoided; manual review required."
            ) % normalized_sku
            _logger.warning(message)
            return {"product": False, "warning": message}

        return {"product": candidate, "warning": False}

    def _link_product_with_woo_id(self, product, woo_id, instance=None):
        self.ensure_one()
        product.ensure_one()
        instance = instance or self
        woo_id_text = str(woo_id or "").strip()
        if not woo_id_text:
            return False

        vals = {}
        if "woo_product_id" in product._fields and (product.woo_product_id or "") != woo_id_text:
            vals["woo_product_id"] = woo_id_text
        if (
            instance
            and "woo_instance_id" in product._fields
            and (not product.woo_instance_id or product.woo_instance_id.id != instance.id)
        ):
            vals["woo_instance_id"] = instance.id
        if vals:
            product.write(vals)
            return True
        return False

    def _normalize_mapping_name(self, name):
        value = (name or "").strip().lower()
        value = re.sub(r"\s+", " ", value)
        value = re.sub(r"[^a-z0-9 _.-]+", "", value)
        return value or False

    def _resolve_mapping_candidate(self, records, mapping_type, label):
        self.ensure_one()
        records = records.exists()
        if not records:
            return False, False
        if len(records) == 1:
            return records[0], False

        message = _(
            "Auto mapping conflict for %(type)s '%(label)s': %(count)s candidates found."
        ) % {
            "type": mapping_type,
            "label": label or "",
            "count": len(records),
        }
        if self.strict_auto_mapping:
            return False, message
        _logger.warning("%s Using first candidate due to non-strict mode.", message)
        return records[0], message

    def _find_matching_payment(self, woo_method, woo_title):
        self.ensure_one()
        normalized = self._normalize_mapping_name(woo_method or woo_title)
        if not normalized:
            return False, False

        model_candidates = []
        if self.env.registry.get("payment.provider"):
            providers = self.env["payment.provider"].sudo().search([])
            exact = providers.filtered(
                lambda r: self._normalize_mapping_name(getattr(r, "code", False)) == normalized
                or self._normalize_mapping_name(getattr(r, "name", False)) == normalized
            )
            if exact:
                model_candidates = exact
        if not model_candidates and self.env.registry.get("account.payment.method"):
            methods = self.env["account.payment.method"].sudo().search([])
            exact = methods.filtered(
                lambda r: self._normalize_mapping_name(getattr(r, "code", False)) == normalized
                or self._normalize_mapping_name(getattr(r, "name", False)) == normalized
            )
            if exact:
                model_candidates = exact

        candidate, warning = self._resolve_mapping_candidate(
            model_candidates,
            "payment_method",
            woo_title or woo_method,
        )
        if candidate:
            return {
                "odoo_model": candidate._name,
                "odoo_res_id": candidate.id,
                "odoo_value": False,
                "warning": warning,
            }, False
        return False, warning

    def _find_matching_shipping(self, shipping_title):
        self.ensure_one()
        normalized = self._normalize_mapping_name(shipping_title)
        if not normalized or not self.env.registry.get("delivery.carrier"):
            return False, False
        carriers = self.env["delivery.carrier"].sudo().search([])
        exact = carriers.filtered(
            lambda r: self._normalize_mapping_name(getattr(r, "name", False)) == normalized
        )
        candidate, warning = self._resolve_mapping_candidate(exact, "shipping_method", shipping_title)
        if candidate:
            return {
                "odoo_model": candidate._name,
                "odoo_res_id": candidate.id,
                "odoo_value": False,
                "warning": warning,
            }, False
        return False, warning

    def _find_matching_tax(self, tax_label, tax_rate=False):
        self.ensure_one()
        if not self.env.registry.get("account.tax"):
            return False, False
        normalized = self._normalize_mapping_name(tax_label)
        taxes = self.env["account.tax"].sudo().search([])
        candidates = taxes
        if tax_rate not in (False, None, ""):
            try:
                rate_float = float(tax_rate)
                candidates = candidates.filtered(lambda t: abs((t.amount or 0.0) - rate_float) < 0.0001)
            except Exception:
                pass
        if normalized:
            name_matches = candidates.filtered(
                lambda t: self._normalize_mapping_name(getattr(t, "name", False)) == normalized
            )
            if name_matches:
                candidates = name_matches
        candidate, warning = self._resolve_mapping_candidate(candidates, "tax", tax_label)
        if candidate:
            return {
                "odoo_model": candidate._name,
                "odoo_res_id": candidate.id,
                "odoo_value": False,
                "warning": warning,
            }, False
        return False, warning

    def _find_matching_category(self, category_name):
        self.ensure_one()
        normalized = self._normalize_mapping_name(category_name)
        if not normalized:
            return False, False
        categories = self.env["product.category"].sudo().search([])
        exact = categories.filtered(
            lambda c: self._normalize_mapping_name(getattr(c, "name", False)) == normalized
        )
        candidate, warning = self._resolve_mapping_candidate(exact, "category", category_name)
        if candidate:
            return {
                "odoo_model": candidate._name,
                "odoo_res_id": candidate.id,
                "odoo_value": False,
                "warning": warning,
            }, False
        if self.auto_create_category_mapping:
            created = self.env["product.category"].sudo().create({"name": category_name})
            return {
                "odoo_model": created._name,
                "odoo_res_id": created.id,
                "odoo_value": False,
                "warning": _("Category '%s' was created for auto mapping.") % category_name,
            }, False
        return False, False

    def _find_matching_tag(self, tag_name):
        self.ensure_one()
        normalized = self._normalize_mapping_name(tag_name)
        if not normalized or not self.env.registry.get("product.tag"):
            return False, False
        tags = self.env["product.tag"].sudo().search([])
        exact = tags.filtered(
            lambda t: self._normalize_mapping_name(getattr(t, "name", False)) == normalized
        )
        candidate, warning = self._resolve_mapping_candidate(exact, "tag", tag_name)
        if candidate:
            return {
                "odoo_model": candidate._name,
                "odoo_res_id": candidate.id,
                "odoo_value": False,
                "warning": warning,
            }, False
        if self.auto_create_tag_mapping:
            created = self.env["product.tag"].sudo().create({"name": tag_name})
            return {
                "odoo_model": created._name,
                "odoo_res_id": created.id,
                "odoo_value": False,
                "warning": _("Tag '%s' was created for auto mapping.") % tag_name,
            }, False
        return False, False

    def _find_matching_order_status(self, woo_status):
        self.ensure_one()
        if not woo_status:
            return False, False
        normalized = self._normalize_mapping_name(woo_status)
        mapping = {
            "pending": "pending",
            "processing": "confirmed",
            "on-hold": "confirmed",
            "completed": "delivered",
            "cancelled": "cancelled",
            "refunded": "refunded",
            "failed": "cancelled",
        }
        return {
            "odoo_model": False,
            "odoo_res_id": False,
            "odoo_value": mapping.get(normalized, "draft"),
            "warning": False,
        }, False

    def _log_auto_mapping(self, status, message, mapping_type=None, woo_label=None, payload_data=None):
        self.ensure_one()
        self._create_sync_report(
            operation="Auto Mapping",
            status=status,
            message=message,
            mode="manual",
            source_action="auto_mapping",
            operation_type=mapping_type or "mapping",
            sync_direction="import",
            woo_id=woo_label or False,
            payload_data=payload_data or {},
            error_message=message if status == "failed" else False,
        )

    def _auto_create_mapping(self, mapping_type, woo_label, match_data):
        self.ensure_one()
        Mapping = self.env["woo.auto.mapping"].sudo()
        normalized_key = self._normalize_mapping_name(woo_label)
        if not normalized_key:
            return False
        existing = Mapping.search(
            [
                ("instance_id", "=", self.id),
                ("mapping_type", "=", mapping_type),
                ("woo_key", "=", normalized_key),
            ],
            limit=1,
        )
        vals = {
            "instance_id": self.id,
            "mapping_type": mapping_type,
            "woo_key": normalized_key,
            "woo_label": woo_label,
            "odoo_model": (match_data or {}).get("odoo_model") or False,
            "odoo_res_id": (match_data or {}).get("odoo_res_id") or False,
            "odoo_value": (match_data or {}).get("odoo_value") or False,
            "auto_created": True,
            "active": True,
            "note": (match_data or {}).get("warning") or False,
        }
        if existing:
            existing.write(vals)
            return existing
        return Mapping.create(vals)

    def _get_auto_mapping(self, mapping_type, woo_label):
        self.ensure_one()
        normalized_key = self._normalize_mapping_name(woo_label)
        if not normalized_key:
            return False
        return self.env["woo.auto.mapping"].sudo().search(
            [
                ("instance_id", "=", self.id),
                ("mapping_type", "=", mapping_type),
                ("woo_key", "=", normalized_key),
                ("active", "=", True),
            ],
            limit=1,
        )

    def _ensure_auto_mapping(self, mapping_type, woo_label, payload_data=None, tax_rate=False):
        self.ensure_one()
        if not woo_label:
            return False
        existing = self._get_auto_mapping(mapping_type, woo_label)
        if existing:
            return existing
        if not self.auto_mapping_creation:
            return False

        finder_map = {
            "payment_method": lambda: self._find_matching_payment(
                payload_data.get("payment_method") if isinstance(payload_data, dict) else woo_label,
                woo_label,
            ),
            "shipping_method": lambda: self._find_matching_shipping(woo_label),
            "tax": lambda: self._find_matching_tax(woo_label, tax_rate=tax_rate),
            "category": lambda: self._find_matching_category(woo_label),
            "tag": lambda: self._find_matching_tag(woo_label),
            "order_status": lambda: self._find_matching_order_status(woo_label),
        }
        finder = finder_map.get(mapping_type)
        if not finder:
            return False

        match_data, warning = finder()
        if warning:
            self._log_auto_mapping(
                status="failed" if self.strict_auto_mapping else "success",
                message=warning,
                mapping_type=mapping_type,
                woo_label=woo_label,
                payload_data=payload_data,
            )
            if self.strict_auto_mapping:
                return False
        if not match_data:
            return False

        mapping = self._auto_create_mapping(mapping_type, woo_label, match_data)
        if mapping:
            target_name = mapping.odoo_display_name or mapping.odoo_value or "N/A"
            message = _(
                "%(type)s '%(woo)s' automatically mapped to '%(odoo)s'."
            ) % {
                "type": dict(mapping._fields["mapping_type"].selection).get(mapping.mapping_type, mapping.mapping_type),
                "woo": woo_label,
                "odoo": target_name,
            }
            self._log_auto_mapping(
                status="success",
                message=message,
                mapping_type=mapping_type,
                woo_label=woo_label,
                payload_data=payload_data,
            )
        return mapping

    def _apply_auto_mappings_from_order_payload(self, order_payload):
        self.ensure_one()
        data = order_payload if isinstance(order_payload, dict) else {}
        if not data:
            return {}

        payment_title = data.get("payment_method_title") or data.get("payment_method")
        if payment_title:
            self._ensure_auto_mapping("payment_method", payment_title, payload_data=data)

        for shipping in data.get("shipping_lines", []) or []:
            if not isinstance(shipping, dict):
                continue
            shipping_label = shipping.get("method_title") or shipping.get("method_id")
            if shipping_label:
                self._ensure_auto_mapping("shipping_method", shipping_label, payload_data=shipping)

        for tax in data.get("tax_lines", []) or []:
            if not isinstance(tax, dict):
                continue
            tax_label = tax.get("label") or tax.get("rate_code")
            tax_rate = tax.get("rate_percent") or tax.get("rate")
            if tax_label:
                self._ensure_auto_mapping("tax", tax_label, payload_data=tax, tax_rate=tax_rate)

        status_text = data.get("status")
        status_mapping = False
        if status_text:
            status_mapping = self._ensure_auto_mapping("order_status", status_text, payload_data=data)
        mapped_order_state = status_mapping.odoo_value if status_mapping else False
        return {"mapped_order_state": mapped_order_state}

    def _apply_auto_mappings_from_product_payload(self, product_payload):
        self.ensure_one()
        data = product_payload if isinstance(product_payload, dict) else {}
        if not data:
            return

        for category in data.get("categories", []) or []:
            if not isinstance(category, dict):
                continue
            category_label = category.get("name")
            if category_label:
                self._ensure_auto_mapping("category", category_label, payload_data=category)

        for tag in data.get("tags", []) or []:
            if not isinstance(tag, dict):
                continue
            tag_label = tag.get("name")
            if tag_label:
                self._ensure_auto_mapping("tag", tag_label, payload_data=tag)

    # =================================================
    # CONNECTION HEALTH CHECK
    # =================================================
    def _health_result(self, check_type, status, message, response_time_ms=None, details=None):
        return {
            "check_type": check_type,
            "status": status,
            "message": message,
            "response_time_ms": response_time_ms,
            "details_json": json.dumps(details or {}, default=str),
        }

    def _check_store_url_validation(self):
        self.ensure_one()
        try:
            normalized = self._get_base_url()
            parsed = urlparse(normalized)
            if parsed.scheme not in ("http", "https") or not parsed.netloc:
                return self._health_result(
                    "store_url_validation",
                    "failed",
                    "Store URL is invalid. Use a valid URL with http/https and host.",
                    details={"shop_url": self.shop_url},
                )

            host = (parsed.hostname or "").lower()
            if host in ("localhost", "127.0.0.1") and parsed.port is None:
                return self._health_result(
                    "store_url_validation",
                    "warning",
                    "Store URL uses localhost without explicit port.",
                    details={"normalized_url": normalized},
                )
            return self._health_result(
                "store_url_validation",
                "success",
                "Store URL format is valid.",
                details={"normalized_url": normalized},
            )
        except Exception as exc:
            return self._health_result(
                "store_url_validation",
                "failed",
                str(exc),
            )

    def _check_api_auth(self):
        self.ensure_one()
        url = f"{self._get_base_url()}/wp-json/wc/v3/products"
        start = perf_counter()
        try:
            response = self._woo_get(url, params={"per_page": 1}, timeout=20)
            elapsed_ms = round((perf_counter() - start) * 1000.0, 2)
            if response.status_code == 200:
                return self._health_result(
                    "api_auth",
                    "success",
                    "API authentication is valid.",
                    response_time_ms=elapsed_ms,
                    details={"status_code": response.status_code},
                )
            return self._health_result(
                "api_auth",
                "failed",
                f"Authentication failed (HTTP {response.status_code}).",
                response_time_ms=elapsed_ms,
                details={"status_code": response.status_code, "response": response.text[:300]},
            )
        except Exception as exc:
            elapsed_ms = round((perf_counter() - start) * 1000.0, 2)
            return self._health_result(
                "api_auth",
                "failed",
                str(exc),
                response_time_ms=elapsed_ms,
            )

    def _check_rest_api_reachability(self):
        self.ensure_one()
        url = f"{self._get_base_url()}/wp-json/wc/v3/system_status"
        start = perf_counter()
        try:
            response = self._woo_get(url, timeout=20)
            elapsed_ms = round((perf_counter() - start) * 1000.0, 2)
            if response.status_code == 200:
                return self._health_result(
                    "api_reachability",
                    "success",
                    "WooCommerce REST API is reachable.",
                    response_time_ms=elapsed_ms,
                    details={"status_code": response.status_code},
                )
            return self._health_result(
                "api_reachability",
                "failed",
                f"REST API unreachable or denied (HTTP {response.status_code}).",
                response_time_ms=elapsed_ms,
                details={"status_code": response.status_code, "response": response.text[:300]},
            )
        except Exception as exc:
            elapsed_ms = round((perf_counter() - start) * 1000.0, 2)
            return self._health_result(
                "api_reachability",
                "failed",
                str(exc),
                response_time_ms=elapsed_ms,
            )

    def _check_read_permission(self):
        self.ensure_one()
        url = f"{self._get_base_url()}/wp-json/wc/v3/products"
        try:
            response = self._woo_get(url, params={"per_page": 1}, timeout=20)
            if response.status_code != 200:
                return self._health_result(
                    "read_permission",
                    "failed",
                    f"Read permission check failed (HTTP {response.status_code}).",
                    details={"status_code": response.status_code, "response": response.text[:300]},
                )

            payload = response.json()
            if isinstance(payload, list):
                return self._health_result(
                    "read_permission",
                    "success",
                    "Read permission is available.",
                    details={"records_returned": len(payload)},
                )
            return self._health_result(
                "read_permission",
                "warning",
                "Read endpoint responded, but payload format is unexpected.",
                details={"payload_type": type(payload).__name__},
            )
        except Exception as exc:
            return self._health_result(
                "read_permission",
                "failed",
                str(exc),
            )

    def _check_write_capability(self):
        self.ensure_one()
        url = f"{self._get_base_url()}/wp-json/wc/v3/products"
        try:
            response = self._woo_options(url, timeout=20)
            code = response.status_code
            allow = response.headers.get("Allow", "") or response.headers.get("allow", "")
            allow_upper = allow.upper()

            if code in (200, 204):
                if "POST" in allow_upper or "PUT" in allow_upper or "PATCH" in allow_upper:
                    return self._health_result(
                        "write_capability",
                        "success",
                        "Write capability appears available (OPTIONS metadata).",
                        details={"status_code": code, "allow": allow},
                    )
                return self._health_result(
                    "write_capability",
                    "warning",
                    "Could not confirm write methods from OPTIONS response.",
                    details={"status_code": code, "allow": allow},
                )
            if code in (401, 403):
                return self._health_result(
                    "write_capability",
                    "failed",
                    f"Write capability denied (HTTP {code}).",
                    details={"status_code": code, "response": response.text[:300]},
                )
            if code in (404, 405):
                return self._health_result(
                    "write_capability",
                    "warning",
                    "Safe write capability probe not supported by server (OPTIONS).",
                    details={"status_code": code},
                )
            return self._health_result(
                "write_capability",
                "warning",
                f"Write capability probe returned HTTP {code}.",
                details={"status_code": code, "response": response.text[:300]},
            )
        except Exception as exc:
            return self._health_result(
                "write_capability",
                "warning",
                f"Write capability probe failed safely: {exc}",
            )

    def _check_webhook_config(self):
        self.ensure_one()
        base_url = (self.env["ir.config_parameter"].sudo().get_param("web.base.url") or "").strip()
        if not base_url:
            return self._health_result(
                "webhook_endpoint",
                "warning",
                "System parameter 'web.base.url' is not configured.",
            )

        webhook_url = f"{base_url.rstrip('/')}/woo/webhook"
        parsed = urlparse(webhook_url)
        if parsed.scheme not in ("http", "https") or not parsed.netloc:
            return self._health_result(
                "webhook_endpoint",
                "failed",
                "Webhook endpoint URL format is invalid.",
                details={"webhook_url": webhook_url},
            )

        return self._health_result(
            "webhook_endpoint",
            "success",
            "Webhook endpoint URL format is valid.",
            details={"webhook_url": webhook_url},
        )

    def _check_woo_version(self):
        self.ensure_one()
        url = f"{self._get_base_url()}/wp-json/wc/v3/system_status"
        try:
            response = self._woo_get(url, timeout=20)
            if response.status_code != 200:
                return self._health_result(
                    "woo_version",
                    "failed",
                    f"Could not detect WooCommerce version (HTTP {response.status_code}).",
                    details={"status_code": response.status_code, "response": response.text[:300]},
                )
            data = response.json()
            version = (data.get("environment") or {}).get("wc_version") if isinstance(data, dict) else False
            if version:
                return self._health_result(
                    "woo_version",
                    "success",
                    f"WooCommerce version detected: {version}.",
                    details={"woo_version": version},
                )
            return self._health_result(
                "woo_version",
                "warning",
                "WooCommerce version not found in system status response.",
            )
        except Exception as exc:
            return self._health_result(
                "woo_version",
                "failed",
                str(exc),
            )

    def _check_currency(self):
        self.ensure_one()
        url = f"{self._get_base_url()}/wp-json/wc/v3/system_status"
        try:
            response = self._woo_get(url, timeout=20)
            if response.status_code != 200:
                return self._health_result(
                    "currency_check",
                    "warning",
                    f"Currency check skipped (HTTP {response.status_code}).",
                )

            data = response.json()
            woo_currency = False
            if isinstance(data, dict):
                env_data = data.get("environment") or {}
                settings_data = data.get("settings") or {}
                woo_currency = env_data.get("currency") or settings_data.get("currency") or settings_data.get("currency_code")

            odoo_currency = (self.env.company.currency_id.name or "").upper()
            woo_currency = (woo_currency or "").upper()

            if not woo_currency:
                return self._health_result(
                    "currency_check",
                    "warning",
                    "Woo currency could not be detected.",
                    details={"odoo_currency": odoo_currency},
                )

            if woo_currency != odoo_currency:
                return self._health_result(
                    "currency_check",
                    "warning",
                    f"Currency mismatch: Woo={woo_currency}, Odoo={odoo_currency}.",
                    details={"woo_currency": woo_currency, "odoo_currency": odoo_currency},
                )

            return self._health_result(
                "currency_check",
                "success",
                f"Currency matches: {woo_currency}.",
                details={"woo_currency": woo_currency, "odoo_currency": odoo_currency},
            )
        except Exception as exc:
            return self._health_result(
                "currency_check",
                "warning",
                f"Currency check failed: {exc}",
            )

    def _measure_response_time(self):
        self.ensure_one()
        url = f"{self._get_base_url()}/wp-json/wc/v3/products"
        start = perf_counter()
        try:
            response = self._woo_get(url, params={"per_page": 1}, timeout=20)
            elapsed_ms = round((perf_counter() - start) * 1000.0, 2)
            if response.status_code == 200:
                return self._health_result(
                    "response_time",
                    "success",
                    f"Measured API response time: {elapsed_ms} ms.",
                    response_time_ms=elapsed_ms,
                )
            return self._health_result(
                "response_time",
                "warning",
                f"Response time measured with HTTP {response.status_code}: {elapsed_ms} ms.",
                response_time_ms=elapsed_ms,
                details={"status_code": response.status_code},
            )
        except Exception as exc:
            elapsed_ms = round((perf_counter() - start) * 1000.0, 2)
            return self._health_result(
                "response_time",
                "failed",
                str(exc),
                response_time_ms=elapsed_ms,
            )

    def _compute_overall_health(self, results):
        statuses = [r.get("status") for r in results]
        if any(status == "failed" for status in statuses):
            return "failed"
        if any(status == "warning" for status in statuses):
            return "warning"
        return "healthy"

    def _run_health_check(self):
        self.ensure_one()
        checks = [
            self._check_store_url_validation,
            self._check_api_auth,
            self._check_rest_api_reachability,
            self._check_read_permission,
            self._check_write_capability,
            self._check_webhook_config,
            self._check_woo_version,
            self._check_currency,
            self._measure_response_time,
        ]

        results = []
        for fn in checks:
            try:
                result = fn()
            except Exception as exc:
                result = self._health_result(fn.__name__, "failed", str(exc))
            results.append(result)

        HealthLog = self.env["woo.connection.health.log"].sudo()
        for row in results:
            try:
                HealthLog.create(
                    {
                        "instance_id": self.id,
                        "check_type": row.get("check_type"),
                        "status": row.get("status"),
                        "message": row.get("message"),
                        "response_time_ms": row.get("response_time_ms"),
                        "details_json": row.get("details_json"),
                    }
                )
            except Exception as log_exc:
                _logger.exception(
                    "Connection health log create failed for instance %s: %s",
                    self.display_name,
                    log_exc,
                )

        overall = self._compute_overall_health(results)
        response_ms = next((r.get("response_time_ms") for r in results if r.get("check_type") == "response_time"), False)
        version_detail = False
        currency_detail = False
        last_error = False
        for r in results:
            if r.get("check_type") == "woo_version":
                try:
                    details = json.loads(r.get("details_json") or "{}")
                    version_detail = details.get("woo_version") or version_detail
                except Exception:
                    pass
            if r.get("check_type") == "currency_check":
                try:
                    details = json.loads(r.get("details_json") or "{}")
                    currency_detail = details.get("woo_currency") or currency_detail
                except Exception:
                    pass
            if r.get("status") == "failed" and not last_error:
                last_error = r.get("message")

        self.write(
            {
                "health_last_checked_at": fields.Datetime.now(),
                "health_overall_status": overall,
                "health_response_time_ms": response_ms or 0.0,
                "health_woo_version": version_detail or False,
                "health_currency": currency_detail or False,
                "health_last_error": last_error or False,
            }
        )
        return results

    def action_run_health_check(self):
        for rec in self:
            results = rec._run_health_check()
            overall = rec.health_overall_status or "warning"
            summary = (
                f"{overall.title()} — "
                f"Success: {len([r for r in results if r.get('status') == 'success'])} | "
                f"Warning: {len([r for r in results if r.get('status') == 'warning'])} | "
                f"Failed: {len([r for r in results if r.get('status') == 'failed'])}"
            )
            rec._create_sync_report(
                operation="Connection Health Check",
                status="failed" if overall == "failed" else "success",
                message=summary,
                mode="manual",
                source_action="connection_health_check",
                operation_type="analytics",
                sync_direction="import",
                payload_data={"results": results, "overall": overall},
                error_message=summary if overall == "failed" else False,
            )

        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("Connection Health Check"),
                "message": summary,
                "type": "success" if overall == "healthy" else ("warning" if overall == "warning" else "danger"),
                "sticky": overall != "healthy",
            },
        }

    def _success_toast(self, title, message):
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": title,
                "message": message,
                "type": "success",
                "sticky": False,
            },
        }

    def fetch_order(self, woo_order_id):
        """
        Fetch a single order from WooCommerce
        """
        self.ensure_one()

        if not self.shop_url or not self.consumer_key or not self.consumer_secret:
            raise UserError("WooCommerce credentials are not configured.")
        base_url = self._get_base_url()
        url = f"{base_url}/wp-json/wc/v3/orders/{woo_order_id}"
        # print("url order 95-",url)

        response = self._woo_get(url, timeout=30)
        # print("response",response)

        if response.status_code != 200:
            raise UserError(
                f"Failed to fetch Woo order {woo_order_id}: {response.text}"
            )

        return response.json()

    # =================================================
    # TEST CONNECTION
    # =================================================
    def action_test_connection(self):
        for rec in self:
            errors = []
            tested_urls = []
            for base_url in rec._test_connection_base_candidates():
                url = f"{base_url}/wp-json/wc/v3/system_status"
                tested_urls.append(url)
                try:
                    r = rec._woo_get(url, timeout=20)
                except Exception as e:
                    errors.append(f"{url} -> {e}")
                    continue

                if r.status_code == 200:
                    if base_url != rec._get_base_url():
                        rec.shop_url = base_url
                    return {
                        "type": "ir.actions.client",
                        "tag": "display_notification",
                        "params": {
                            "title": "Connected",
                            "message": f"WooCommerce connection successful ({base_url}).",
                            "type": "success",
                            "sticky": False,
                        },
                    }

                if r.status_code in (401, 403):
                    raise UserError(
                        "Connection reached WooCommerce, but authentication failed.\n"
                        f"URL: {url}\n"
                        "Check consumer key/secret permissions (Read/Write), or WP app credentials."
                    )

                errors.append(f"{url} -> HTTP {r.status_code}: {r.text}")

            hint = ""
            normalized = rec._get_base_url()
            parsed = urlparse(normalized)
            host = (parsed.hostname or "").lower()
            if host in ("localhost", "127.0.0.1") and parsed.port is None:
                hint = (
                    "\nTip: your Shop URL uses localhost without a port. "
                    "Set explicit WordPress port, for example: "
                    "http://localhost:8080/woocommerce/wordpress"
                )

            details = "\n".join(errors) if errors else "\n".join(tested_urls)
            raise UserError(
                "Connection error:\n"
                f"{details}"
                f"{hint}"
            )

    def auto_sync_all(self, force=True):
        self.ensure_one()

        status = self.env["woo.sync.status"].search(
            [("instance_id", "=", self.id)], limit=1
        )
        if not status:
            status = self.env["woo.sync.status"].create({
                "instance_id": self.id,
            })

        # ⛔ Prevent parallel sync
        if status.syncing:
            return False

        # ⏱ Skip if recently synced (10 min)
        if (
                not force
                and status.last_sync
                and fields.Datetime.now()
                < status.last_sync + timedelta(minutes=10)
        ):
            return False

        # 📝 CREATE AUTO SYNC REPORT (START)
        report = self.env["woo.report"].create({
                "instance_id": self.id,
                "operation": "Auto Sync",
                "status": "running",
                "message": "Auto sync started",
                "auto": True,
                "mode": "cron",
            })

        try:
            status.syncing = True

            # 🔥 RUN ALL SYNC TASKS
            # self.action_sync_products()
            # self.action_sync_categories()
            # self.action_sync_orders()
            if self.cron_sync_products:
                self.action_sync_products()

            if self.cron_sync_categories:
                self.action_sync_categories()

            if self.cron_sync_orders:
                self.action_sync_orders()

            # customers handled via orders

            status.write({
                "last_sync": fields.Datetime.now(),
                "last_error": False,
                "syncing": False,
            })

            # ✅ UPDATE AUTO SYNC REPORT (SUCCESS)
            report.write({
                "status": "success",
                "message": "Auto sync completed successfully",
            })

            return True

        except Exception as e:
            status.write({
                "last_error": str(e),
                "syncing": False,
            })

            # ❌ UPDATE AUTO SYNC REPORT (FAILED)
            report.write({
                "status": "failed",
                "message": str(e),
            })

            raise UserError(str(e))

    def action_sync_products(self):
        self.ensure_one()

        WooProduct = self.env["woo.product.sync"]
        ProductTemplate = self.env["product.template"]

        synced = 0
        sku_linked = 0
        sku_conflicts = 0

        try:
            products = self.fetch_products()

            for p in products:
                if not isinstance(p, dict):
                    _logger.warning(
                        "Skipping malformed Woo product payload for instance %s: %s",
                        self.display_name,
                        type(p).__name__,
                    )
                    continue

                woo_id = p.get("id")
                if not woo_id:
                    continue

                self._apply_auto_mappings_from_product_payload(p)

                name = p.get("name")
                sku = p.get("sku") or p.get("slug")
                normalized_sku = self._normalize_sku(sku)

                # -----------------------------------------
                # 1️⃣ FIND OR CREATE PRODUCT
                # -----------------------------------------
                product = ProductTemplate.search(
                    [
                        ("woo_product_id", "=", str(woo_id)),
                        ("woo_instance_id", "in", [False, self.id]),
                    ],
                    limit=1,
                )

                if not product and self.smart_sku_matching and normalized_sku:
                    try:
                        match_info = self._find_odoo_product_by_sku(normalized_sku, instance=self)
                        product = match_info.get("product_tmpl")
                        warning = match_info.get("warning")
                        if warning:
                            sku_conflicts += 1
                            self._create_sync_report(
                                operation="Product Sync",
                                status="failed",
                                message=warning,
                                source_action="smart_sku_matching",
                                operation_type="product",
                                sync_direction="import",
                                woo_id=str(woo_id),
                                payload_data=p,
                                error_message=warning,
                            )
                        if product:
                            self._link_product_with_woo_id(product, woo_id, instance=self)
                            sku_linked += 1
                            match_msg = _(
                                "Product matched by SKU %(sku)s and Woo ID %(woo)s was linked."
                            ) % {"sku": normalized_sku, "woo": woo_id}
                            _logger.info(match_msg)
                    except Exception as match_exc:
                        sku_conflicts += 1
                        warning_message = str(match_exc)
                        self._create_sync_report(
                            operation="Product Sync",
                            status="failed",
                            message=warning_message,
                            source_action="smart_sku_matching",
                            operation_type="product",
                            sync_direction="import",
                            woo_id=str(woo_id),
                            payload_data=p,
                            error_message=warning_message,
                        )
                        _logger.warning(
                            "Smart SKU matching failed for Woo product %s (SKU: %s): %s",
                            woo_id,
                            normalized_sku,
                            warning_message,
                        )
                        continue

                if not product:
                    product = ProductTemplate.create({
                        "name": name,
                        "default_code": normalized_sku,
                        "sale_ok": True,
                        "purchase_ok": True,
                    })

                # -----------------------------------------
                # 2️⃣ SAFE FALLBACK
                # -----------------------------------------
                sale_price_raw = p.get("sale_price")
                regular_price_raw = p.get("regular_price")
                effective_sale_price = (
                    float(sale_price_raw)
                    if sale_price_raw not in (None, "")
                    else float(regular_price_raw or 0.0)
                )
                product_vals = {
                    "name": name,
                    "default_code": normalized_sku or product.default_code,
                    # Odoo Sale Price should follow latest Woo sale price when available.
                    "list_price": effective_sale_price,
                }
                if "sale_price" in ProductTemplate._fields:
                    product_vals["sale_price"] = float(sale_price_raw or 0.0)
                product.write(product_vals)
                self._link_product_with_woo_id(product, woo_id, instance=self)

                # -----------------------------------------
                # 3️⃣ WOO SYNC RECORD
                # -----------------------------------------
                # vals = {
                #     "instance_id": self.id,  # ✅ ADD THIS LINE
                #     "woo_product_id": str(woo_id),
                #     "product_tmpl_id": product.id,
                #     "name": product.name,
                #     "state": "synced",
                #     "synced_on": fields.Datetime.now(),
                # }
                # -----------------------------------------
                # 4️⃣ WOO SYNC RECORD (FULL DATA)
                # -----------------------------------------

                # Categories
                category_ids = []
                for c in p.get("categories", []):
                    if not isinstance(c, dict):
                        continue
                    category = self.env["product.category"].search(
                        [("name", "=", c.get("name"))],
                        limit=1
                    )
                    if not category:
                        category = self.env["product.category"].create({
                            "name": c.get("name")
                        })
                    category_ids.append(category.id)

                # Tags
                tag_ids = []
                for t in p.get("tags", []):
                    if not isinstance(t, dict):
                        continue
                    tag = self.env["product.tag"].search(
                        [("name", "=", t.get("name"))],
                        limit=1
                    )
                    if not tag:
                        tag = self.env["product.tag"].create({
                            "name": t.get("name")
                        })
                    tag_ids.append(tag.id)
                published_date = False
                woo_date = p.get("date_created")

                if woo_date:
                    try:
                        published_date = datetime.fromisoformat(
                            woo_date.replace("Z", "+00:00")
                        ).strftime("%Y-%m-%d %H:%M:%S")
                    except Exception:
                        published_date = False

                vals = {
                    "instance_id": self.id,
                    "woo_product_id": str(woo_id),

                    # Identity
                    "product_tmpl_id": product.id,
                    "name": p.get("name"),
                    "sku": normalized_sku,

                    # Pricing
                    "list_price": effective_sale_price,
                    "sale_price": float(sale_price_raw or 0.0),

                    # Stock
                    "manage_stock": p.get("manage_stock", False),
                    "qty_available": float(p.get("stock_quantity") or 0.0),
                    "stock_status": p.get("stock_status"),

                    # Classification
                    "category_ids": [(6, 0, category_ids)],
                    "tag_ids": [(6, 0, tag_ids)],

                    # Meta
                    "published_date": published_date,
                    "state": "synced",
                    "synced_on": fields.Datetime.now(),
                }

                existing = WooProduct.search(
                    [
                        ("woo_product_id", "=", str(woo_id)),
                        ("instance_id", "=", self.id),
                    ],
                    limit=1
                )

                if existing:
                    existing.write(vals)
                    sync_record = existing
                else:
                    sync_record = WooProduct.create(vals)

                # Apply product mapping to Woo sync model fields.
                self._apply_field_mapping(
                    model="product",
                    woo_data=p,
                    record=sync_record,
                )

                synced += 1

            self._create_sync_report(
                operation="Product Sync",
                status="success",
                message=(
                    f"{synced} products synced successfully. "
                    f"SKU linked: {sku_linked}. "
                    f"SKU conflicts/warnings: {sku_conflicts}."
                ),
            )

            return {
                "type": "ir.actions.client",
                "tag": "display_notification",
                "params": {
                    "title": "Products Synced",
                    "message": (
                        f"{synced} products synced successfully. "
                        f"SKU linked: {sku_linked}. "
                        f"Warnings: {sku_conflicts}."
                    ),
                    "sticky": False,
                },
            }

        except Exception as e:
            self._create_sync_report(
                operation="Product Sync",
                status="failed",
                message=str(e),
            )
            raise UserError(str(e))

    # =================================================
    # SYNC CUSTOMERS
    # =================================================

    def _sync_customer_from_order(self, order):
        """
        Create or update Woo customer from order billing data
        and apply customer field mapping
        """
        WooCustomer = self.env["woo.customer.sync"]

        billing = order.get("billing") or {}
        email = (billing.get("email") or "").strip().lower()

        # Skip orders without email
        if not email:
            return False

        # ✅ Always generate a stable woo_customer_id
        customer_id = order.get("customer_id")
        if customer_id and customer_id != 0:
            woo_customer_id = str(customer_id)
        else:
            # Guest checkout fallback
            woo_customer_id = f"guest_{email}"

        vals = {
            "instance_id": self.id,
            "woo_customer_id": woo_customer_id,
            "name": (
                    f"{billing.get('first_name', '')} {billing.get('last_name', '')}".strip()
                    or email
            ),
            "email": email,
            "phone": billing.get("phone"),
            "state": "synced",
            "synced_on": fields.Datetime.now(),
        }

        customer = WooCustomer.search(
            [
                ("woo_customer_id", "=", woo_customer_id),
                ("instance_id", "=", self.id),
            ],
            limit=1,
        )

        if customer:
            customer.write(vals)
        else:
            customer = WooCustomer.create(vals)

        # 🔥 APPLY CUSTOMER FIELD MAPPING (THIS WAS MISSING)
        # Mapping source = Woo order payload
        self._apply_field_mapping(
            model="customer",
            woo_data=order,
            record=customer,
        )

        return customer

    def action_sync_customers(self):
        self.ensure_one()
        WooCustomer = self.env["woo.customer.sync"]
        synced = 0

        try:
            wcapi = self._get_wcapi(self)
            response = wcapi.get("customers", params={"per_page": 100})

            if response.status_code != 200:
                raise UserError(response.text)

            for c in response.json():
                woo_id = c.get("id")
                email = (c.get("email") or "").strip().lower()
                first = c.get("first_name") or ""
                last = c.get("last_name") or ""

                vals = {
                    "instance_id": self.id,
                    "woo_customer_id": str(woo_id) if woo_id else (f"guest_{email}" if email else False),
                    "name": f"{first} {last}".strip() or email or f"Customer {woo_id}",
                    "email": email,
                    "phone": (c.get("billing") or {}).get("phone"),
                    "state": "synced",
                    "synced_on": fields.Datetime.now(),
                }

                if not vals["woo_customer_id"]:
                    continue

                existing = WooCustomer.search(
                    [
                        ("woo_customer_id", "=", vals["woo_customer_id"]),
                        ("instance_id", "=", self.id),
                    ],
                    limit=1,
                )
                if existing:
                    existing.write(vals)
                    customer = existing
                else:
                    customer = WooCustomer.create(vals)

                self._apply_field_mapping(
                    model="customer",
                    woo_data=c,
                    record=customer,
                )

                synced += 1

            self._create_sync_report(
                operation="Customer Sync",
                status="success",
                message=f"{synced} customers synced successfully",
            )

            return self._success_toast(
                "Customers Synced",
                f"{synced} customers synced successfully."
            )
        except Exception as e:
            self._create_sync_report(
                operation="Customer Sync",
                status="failed",
                message=str(e),
            )
            raise UserError(str(e))

    def action_sync_orders(self):
        self.ensure_one()
        WooOrder = self.env["woo.order.sync"]
        synced = 0

        try:
            self.env.cr.execute(
                """
                DELETE FROM woo_order_sync a
                USING woo_order_sync b
                WHERE a.id < b.id
                  AND a.instance_id = b.instance_id
                  AND a.woo_order_id = b.woo_order_id
                  AND a.woo_order_id IS NOT NULL
                  AND a.instance_id = %s
                """,
                (self.id,),
            )

            wcapi = self._get_wcapi(self)
            response = wcapi.get("orders", params={"per_page": 100})

            if response.status_code != 200:
                raise UserError(response.text)

            for o in response.json():
                woo_id = o.get("id")
                if not woo_id:
                    continue

                billing = o.get("billing") or {}
                mapping_context = self._apply_auto_mappings_from_order_payload(o)

                # 🔥 CUSTOMER SYNC (ALREADY GOOD)
                partner = self._sync_customer_from_order(o)

                vals = {
                    "woo_order_id": str(woo_id),
                    "name": o.get("number"),
                    "customer_name": f"{billing.get('first_name', '')} {billing.get('last_name', '')}",
                    "customer_email": billing.get("email"),
                    "total_amount": float(o.get("total", 0.0)),
                    "currency": o.get("currency"),
                    "status": o.get("status"),
                    "payment_method": o.get("payment_method"),
                    "payment_method_title": o.get("payment_method_title"),
                    "date_created": self._parse_woo_datetime(
                        o.get("date_created")
                    ),
                    "state": "synced",
                    "synced_on": fields.Datetime.now(),
                    "instance_id": self.id,
                    "order_state": (mapping_context or {}).get("mapped_order_state") or "draft",
                }

                existing = WooOrder.search(
                    [
                        ("woo_order_id", "=", str(woo_id)),
                        ("instance_id", "=", self.id),
                    ],
                    order="synced_on desc, id desc",
                )

                if existing:
                    order_sync = existing[0]
                    if len(existing) > 1:
                        (existing - order_sync).unlink()
                    order_sync.write(vals)
                else:
                    order_sync = WooOrder.create(vals)

                # 🔥 APPLY ORDER FIELD MAPPING (THIS WAS MISSING)
                self._apply_field_mapping(
                    model="order",
                    woo_data=o,
                    record=order_sync,
                )

                # 🔥 ORDER LINES
                order_sync.sync_order_lines(order_sync, o)

                synced += 1

            WooOrder._cleanup_duplicates(self.id)

            self._create_sync_report(
                "Order Sync", "success",
                f"{synced} orders synced"
            )

            return self._success_toast(
                "Orders Synced",
                f"{synced} orders synced successfully."
            )

        except Exception as e:
            self._create_sync_report("Order Sync", "failed", str(e))
            raise UserError(str(e))

    # =================================================
    # SYNC CATEGORIES
    # =================================================

    def action_sync_categories(self):
        self.ensure_one()
        WooCategory = self.env["woo.category.sync"]
        synced = 0

        try:
            wcapi = self._get_wcapi(self)
            response = wcapi.get("products/categories", params={"per_page": 100})

            if response.status_code != 200:
                raise UserError(response.text)

            for c in response.json():
                woo_id = c.get("id")
                if not woo_id:
                    continue
                if c.get("name"):
                    self._ensure_auto_mapping("category", c.get("name"), payload_data=c)

                vals = {
                    "name": c.get("name"),
                    "woo_category_id": str(woo_id),
                    "parent_woo_id": str(c.get("parent")) if c.get("parent") else False,
                    "slug": c.get("slug"),
                    "description": c.get("description"),
                    "product_count": c.get("count", 0),
                    "state": "synced",
                    "synced_on": fields.Datetime.now(),
                    "instance_id": self.id,
                }

                existing = WooCategory.search(
                    [
                        ("woo_category_id", "=", str(woo_id)),
                        ("instance_id", "=", self.id),
                    ],
                    limit=1
                )

                if existing:
                    existing.write(vals)
                    category = existing
                else:
                    category = WooCategory.create(vals)

                # 🔥 APPLY CATEGORY FIELD MAPPING (THIS WAS MISSING)
                self._apply_field_mapping(
                    model="category",
                    woo_data=c,
                    record=category,
                )

                synced += 1

            self._create_sync_report(
                operation="Category Sync",
                status="success",
                message=f"{synced} categories synced successfully",
            )

            return self._success_toast(
                "Categories Synced",
                f"{synced} categories synced successfully."
            )

        except Exception as e:
            self._create_sync_report(
                operation="Category Sync",
                status="failed",
                message=str(e),
            )
            raise UserError(str(e))

    # =================================================
    # SYNC COUPONS
    # =================================================
    def action_sync_coupons(self):
        self.ensure_one()
        WooCoupon = self.env["woo.coupon.sync"]
        synced = 0

        try:
            wcapi = self._get_wcapi(self)
            response = wcapi.get("coupons", params={"per_page": 100})

            if response.status_code != 200:
                raise UserError(response.text)

            for c in response.json():
                woo_id = c.get("id")
                if not woo_id:
                    continue

                vals = {
                    "instance_id": self.id,
                    "name": c.get("code"),
                    "woo_coupon_id": str(woo_id),
                    "discount_type": c.get("discount_type"),
                    "amount": float(c.get("amount") or 0.0),
                    "usage_limit": c.get("usage_limit"),
                    "usage_count": c.get("usage_count"),
                    "expiry_date": self._parse_woo_datetime(c.get("date_expires")),
                    "status": c.get("status"),
                    "state": "synced",
                    "synced_on": fields.Datetime.now(),
                }

                existing = WooCoupon.search(
                    [
                        ("woo_coupon_id", "=", str(woo_id)),
                        ("instance_id", "=", self.id),
                    ],
                    limit=1
                )
                if existing:
                    existing.write(vals)
                else:
                    WooCoupon.create(vals)

                synced += 1

            # ✅ REPORT ENTRY
            self._create_sync_report(
                operation="Coupon Sync",
                status="success",
                message=f"{synced} coupons synced successfully",
            )

            return self._success_toast(
                "Coupons Synced",
                f"{synced} coupons synced successfully."
            )

        except Exception as e:
            # ❌ FAILURE REPORT
            self._create_sync_report(
                operation="Coupon Sync",
                status="failed",
                message=str(e),
            )
            raise UserError(str(e))

    def action_inventory_report(self):
        raise UserError("Inventory report will be implemented next.")

    def action_sync_reports(self):
        """
        Sync WooCommerce Analytics data:
        - Total Orders
        - Total Revenue
        - Total Customers
        - Total Products
        """
        self.ensure_one()

        base_url = self.shop_url.rstrip("/") + "/wp-json/wc/v3"
        auth = (self.consumer_key, self.consumer_secret)

        try:
            # -----------------------------
            # 1️⃣ TOTAL ORDERS
            # -----------------------------
            orders_resp = requests.get(
                f"{base_url}/orders",
                auth=auth,
                params={"per_page": 1},
                timeout=30,
            )
            orders_resp.raise_for_status()
            total_orders = int(orders_resp.headers.get("X-WP-Total", 0))

            # -----------------------------
            # 2️⃣ TOTAL PRODUCTS
            # -----------------------------
            products_resp = requests.get(
                f"{base_url}/products",
                auth=auth,
                params={"per_page": 1},
                timeout=30,
            )
            products_resp.raise_for_status()
            total_products = int(products_resp.headers.get("X-WP-Total", 0))

            # -----------------------------
            # 3️⃣ TOTAL CUSTOMERS
            # -----------------------------
            customers_resp = requests.get(
                f"{base_url}/customers",
                auth=auth,
                params={"per_page": 1},
                timeout=30,
            )
            customers_resp.raise_for_status()
            total_customers = int(customers_resp.headers.get("X-WP-Total", 0))

            # -----------------------------
            # 4️⃣ TOTAL REVENUE
            # -----------------------------
            revenue_resp = requests.get(
                f"{base_url}/reports/sales",
                auth=auth,
                timeout=30,
            )
            revenue_resp.raise_for_status()
            revenue_data = revenue_resp.json()
            total_revenue = float(revenue_data[0].get("total_sales", 0.0)) if revenue_data else 0.0

            # -----------------------------
            # 5️⃣ SAVE LAST SYNC
            # -----------------------------
            self.write({
                "total_orders": total_orders,
                "total_products": total_products,
                "total_customers": total_customers,
                "total_revenue": total_revenue,
                "last_sync": fields.Datetime.now(),
            })

            # -----------------------------
            # 6️⃣ CREATE REPORT LOG
            # -----------------------------
            self._create_sync_report(
                operation="Analytics Sync",
                status="success",
                message=(
                    f"Orders: {total_orders}, "
                    f"Products: {total_products}, "
                    f"Customers: {total_customers}, "
                    f"Revenue: {total_revenue}"
                ),
            )

            # -----------------------------
            # 7️⃣ TOAST MESSAGE
            # -----------------------------
            return {
                "type": "ir.actions.client",
                "tag": "display_notification",
                "params": {
                    "title": _("WooCommerce Analytics"),
                    "message": _("Analytics synced successfully"),
                    "type": "success",
                    "sticky": False,
                },
            }

        except Exception as e:
            # -----------------------------
            # ERROR REPORT
            # -----------------------------
            self._create_sync_report(
                operation="Analytics Sync2",
                status="failed",
                message=str(e),
            )
            raise UserError(_("Analytics sync failed:\n%s") % e)

    def _create_sync_report(
            self,
            operation,
            status,
            message="",
            mode="manual",
            source_action=None,
            reference=None,
            operation_type=None,
            sync_direction=None,
            woo_id=None,
            payload_data=None,
            error_message=None,
            webhook_log_id=None,
    ):
        payload_json = False
        if payload_data not in (None, False, ""):
            try:
                payload_json = json.dumps(payload_data, default=str)
            except Exception:
                payload_json = json.dumps({"raw_payload": str(payload_data)})

        report = self.env["woo.report"].create({
            "instance_id": self.id,
            "operation": operation,
            "status": status,
            "message": message,
            "error_message": error_message if error_message is not None else (message if status == "failed" else False),
            "mode": mode,
            "source_action": source_action,
            "reference": reference,
            "operation_type": operation_type,
            "sync_direction": sync_direction,
            "woo_id": woo_id or reference,
            "payload_json": payload_json,
            "webhook_log_id": webhook_log_id.id if hasattr(webhook_log_id, "id") else webhook_log_id or False,
        })

        self.env["woo.report.line"].create({
            "report_id": report.id,
            "record_type": operation,
            "source_action": source_action or mode,
            "woo_id": reference or False,
            "name": message or operation,
            "status": "success" if status == "success" else "error",
            "error_message": message if status == "failed" else False,
        })

        # Push a live dashboard refresh event to connected web clients.
        try:
            if "bus.bus" in self.env:
                self.env["bus.bus"]._sendone(
                    "broadcast",
                    "woo_dashboard_update",
                    {
                        "instance_id": self.id,
                        "mode": mode,
                        "source_action": source_action or mode,
                        "status": status,
                        "reference": reference,
                    },
                )
        except Exception as e:
            _logger.debug("Failed to push Woo dashboard update event: %s", e)

        return report

    def _map_values(self, mappings, woo_data):
        vals = {}

        for mapping in mappings:
            woo_key = mapping.woo_field_key
            odoo_field = mapping.odoo_field_id.name

            # -----------------------------
            # PRICE FALLBACK LOGIC
            # -----------------------------
            if woo_key == "price":
                value = (
                        woo_data.get("sale_price")
                        or woo_data.get("regular_price")
                        or woo_data.get("price")
                )
            else:
                if woo_key not in woo_data:
                    continue
                value = woo_data.get(woo_key)

            if value in (None, "", [], {}):
                continue

            # Convert price fields
            if odoo_field in ("list_price", "standard_price"):
                try:
                    value = float(value)
                except Exception:
                    continue

            # Name safety
            if odoo_field == "name":
                value = str(value)

            vals[odoo_field] = value

        return vals

    def _has_product_specific_mapping(self, product, woo_key, odoo_field):
        Mapping = self.env["woo.field.mapping"]
        return bool(Mapping.search_count([
            ("instance_id", "=", self.id),
            ("model", "=", "product"),
            ("product_tmpl_id", "=", product.id),
            ("woo_field_key", "=", woo_key),
            ("odoo_field_id.name", "=", odoo_field),
            ("active", "=", True),
        ]))

    #     # ------------------------------------------------
    #     # FETCH PRODUCTS (QUERY PARAM AUTH – LOCALHOST SAFE)
    #     # ------------------------------------------------

    def fetch_products(self):
        self.ensure_one()

        if not self.shop_url:
            raise UserError("Shop URL is not configured")

        base_url = self._get_base_url()
        url = f"{base_url}/wp-json/wc/v3/products"

        response = self._woo_get(url, timeout=30)

        # params = {
        #     "consumer_key": self.consumer_key,
        #     "consumer_secret": self.consumer_secret,
        #     "per_page": 100,
        # }
        #
        # response = requests.get(url, params=params, timeout=30)

        if response.status_code == 401:
            raise UserError(
                "Unauthorized (401).\n"
                "Check Woo REST API key permissions (must be READ)."
            )

        response.raise_for_status()
        payload = response.json()

        # WooCommerce list endpoints should return a list, but some stacks/plugins
        # can wrap data in a dict or return non-dict rows.
        if isinstance(payload, dict):
            if isinstance(payload.get("data"), list):
                payload = payload.get("data")
            elif isinstance(payload.get("products"), list):
                payload = payload.get("products")
            else:
                raise UserError(
                    "Unexpected Woo products response format. "
                    "Expected a list of products."
                )

        if not isinstance(payload, list):
            raise UserError(
                "Unexpected Woo products response format. "
                "Expected a list of products."
            )

        # Keep only dict items so sync logic using .get(...) remains safe.
        return [item for item in payload if isinstance(item, dict)]

    def fetch_sample_product(self):
        self.ensure_one()

        base_url = self._get_base_url()
        url = f"{base_url}/wp-json/wc/v3/products"

        response = self._woo_get(url, params={"per_page": 1}, timeout=30)

        if response.status_code == 401:
            raise UserError("Woo API Unauthorized (401)")

        response.raise_for_status()
        products = response.json()
        return products[0] if products else {}

    def action_sync_woo_fields(self):
        self.ensure_one()

        WooField = self.env["woo.field"]

        sample = self.fetch_sample_product()
        if not isinstance(sample, dict):
            return

        for key in sample.keys():
            WooField.search([
                ("instance_id", "=", self.id),
                ("model", "=", "product"),
                ("name", "=", key),
            ], limit=1) or WooField.create({
                "instance_id": self.id,
                "model": "product",
                "name": key,
            })

    # def _get_base_url(self):
    #     self.ensure_one()
    #     if not self.shop_url:
    #         raise UserError("Shop URL is not configured")
    #     return self.shop_url.rstrip("/")
    def _get_base_url(self):
        self.ensure_one()

        if not self.shop_url:
            raise UserError("Shop URL is not configured")

        return self._normalize_shop_url_value(self.shop_url)

    def _extract_mapped_values(self, woo_data, mappings):
        vals = {}

        for woo_key, odoo_field in mappings.items():
            value = woo_data.get(woo_key)

            if value in (None, "", False):
                continue

            vals[odoo_field] = value

        return vals

    def _get_field_mappings(self, model):
        mappings = self.env["woo.field.mapping"].search([
            ("instance_id", "=", self.id),
            ("model", "=", model),
            ("active", "=", True),
        ])

        return {
            m.woo_field_key.name: m.odoo_field_id.name
            for m in mappings
        }

    def _normalize_woo_mapping_key(self, key):
        aliases = {
            "qty_available": "stock_quantity",
            "list_price": "regular_price",
            "product_name": "name",
        }
        return aliases.get(key, key)

    def _coerce_mapping_value(self, field, value):
        if value in (None, "", False):
            return None

        if field.type in ("float", "monetary"):
            try:
                return float(value)
            except Exception:
                return None

        if field.type == "integer":
            try:
                return int(float(value))
            except Exception:
                return None

        if field.type == "boolean":
            if isinstance(value, bool):
                return value
            if isinstance(value, str):
                return value.strip().lower() in ("1", "true", "yes", "y", "instock")
            return bool(value)

        if field.type in ("char", "text", "html", "selection"):
            return str(value)

        return value

    def _protected_mapping_fields(self, model):
        """Prevent mapping from overwriting identity/core sync fields."""
        protected = {
            "product": {
                "instance_id",
                "woo_product_id",
                "product_tmpl_id",
            },
            "customer": {
                "instance_id",
                "woo_customer_id",
            },
            "order": {
                "instance_id",
                "woo_order_id",
                "name",
            },
            "category": {
                "instance_id",
                "woo_category_id",
            },
        }
        return protected.get(model, set())

    def _apply_field_mapping(self, model, woo_data, record):
        mappings = self._get_field_mappings(model)
        vals = {}
        record_fields = record._fields
        protected_fields = self._protected_mapping_fields(model)

        for woo_key, odoo_field in mappings.items():
            value = self._get_nested_value(woo_data, woo_key)

            if (
                odoo_field in record_fields
                and odoo_field not in protected_fields
                and not record_fields[odoo_field].readonly
            ):
                value = self._coerce_mapping_value(record_fields[odoo_field], value)
                if value not in (None, "", False):
                    vals[odoo_field] = value

        if vals:
            record.write(vals)


        return vals

    def fetch_sample_data(self, model):
        self.ensure_one()

        if model == "product":
            return self.fetch_sample_product()

        if model == "order":
            return self.fetch_sample_order()

        if model == "customer":
            return self.fetch_sample_customer()

        if model == "category":
            return self.fetch_sample_category()

        return {}

    def fetch_sample_order(self):
        self.ensure_one()

        base_url = self._get_base_url()
        url = f"{base_url}/wp-json/wc/v3/orders"

        _logger.info("Fetching sample Woo order from %s", url)

        response = self._woo_get(url, params={"per_page": 1}, timeout=30)

        if response.status_code == 401:
            raise UserError("Woo API Unauthorized (401)")

        response.raise_for_status()
        orders = response.json()

        return orders[0] if orders else {}

    def fetch_sample_customer(self):
        self.ensure_one()

        base_url = self._get_base_url()
        url = f"{base_url}/wp-json/wc/v3/customers"

        _logger.info("Fetching sample Woo customer from %s", url)

        response = self._woo_get(url, params={"per_page": 1}, timeout=30)

        if response.status_code == 401:
            raise UserError("Woo API Unauthorized (401)")

        response.raise_for_status()
        customers = response.json()

        return customers[0] if customers else {}

    def fetch_sample_category(self):
        self.ensure_one()

        base_url = self._get_base_url()
        url = f"{base_url}/wp-json/wc/v3/products/categories"

        response = self._woo_get(url, params={"per_page": 1}, timeout=30)

        if response.status_code == 401:
            raise UserError("Woo API Unauthorized (401)")

        response.raise_for_status()
        categories = response.json()

        return categories[0] if categories else {}

    def _get_nested_value(self, data, key):
        """
        Supports nested Woo keys like:
        billing.email
        shipping.first_name
        """
        if not data or not key:
            return None

        key = self._normalize_woo_mapping_key(key)
        value = data
        for part in key.split("."):
            if isinstance(value, dict):
                value = value.get(part)
            else:
                return None
        return value

    def sync_inventory_from_woo(self):
        self.ensure_one()
        Inventory = self.env["woo.inventory"]
        synced = 0

        wcapi = self._get_wcapi(self)
        response = wcapi.get("products", params={"per_page": 100})

        if response.status_code != 200:
            raise UserError(response.text)

        for p in response.json():
            woo_id = str(p.get("id"))

            manage_stock = p.get("manage_stock")
            stock_status = p.get("stock_status")

            if manage_stock:
                quantity = int(p.get("stock_quantity") or 0)
            else:
                quantity = 1 if stock_status == "instock" else 0

            vals = {
                "instance_id": self.id,
                "woo_product_id": woo_id,
                "product_name": p.get("name"),
                "sku": p.get("sku"),
                "quantity": quantity,
            }

            record = Inventory.search(
                [
                    ("woo_product_id", "=", woo_id),
                    ("instance_id", "=", self.id),
                ],
                limit=1,
            )

            if record:
                record.write(vals)
            else:
                Inventory.create(vals)

            synced += 1

        if self.env.context.get("suppress_toast"):
            return synced

        # ✅ SUCCESS POPUP
        return self._success_toast(
            "Inventory Synced",
            f"{synced} products inventory synced successfully"
        )

    def cron_auto_sync_all_instances(self):
        """
        Cron job:
        Automatically sync all active Woo instances
        """
        instances = self.search([
            ("active", "=", True),
        ])

        _logger.info(
            "Woo Cron (auto_sync_all) started for %s instances: %s",
            len(instances),
            ", ".join(instances.mapped("name")) or "none",
        )

        for instance in instances:
            try:
                instance.auto_sync_all(force=False)
            except Exception as e:
                # ❌ NEVER crash cron
                _logger.error(
                    "Woo auto sync failed for instance %s: %s",
                    instance.name,
                    e,
                )

    # =================================================
    # CRON : AUTO SYNC (SHOPIFY-LIKE)
    # =================================================
    def _is_time_to_sync(self, last_sync, interval_type):
        if not last_sync:
            return True

        now = fields.Datetime.now()
        if interval_type == "hours":
            return now >= last_sync + timedelta(hours=1)
        if interval_type == "days":
            return now >= last_sync + timedelta(days=1)
        if interval_type == "weeks":
            return now >= last_sync + timedelta(days=7)
        if interval_type == "months":
            return now >= last_sync + relativedelta(months=1)
        return False

    def cron_auto_sync(self):
        now = fields.Datetime.now()
        instances = self.search([("active", "=", True)])
        _logger.info(
            "Woo Cron (auto_sync) tick for %s instances: %s",
            len(instances),
            ", ".join(instances.mapped("name")) or "none",
        )

        for instance in instances:
            report = False
            executed = []
            try:
                if instance.auto_product_sync and instance._is_time_to_sync(
                    instance.last_product_sync_at,
                    instance.auto_product_interval_type,
                ):
                    if not report:
                        report = self.env["woo.report"].create({
                            "instance_id": instance.id,
                            "operation": "Auto Sync (Cron)",
                            "status": "running",
                            "message": "Auto sync started",
                            "auto": True,
                            "mode": "cron",
                        })
                    instance.action_sync_products()
                    instance.last_product_sync_at = now
                    executed.append("products")

                if instance.auto_customer_sync and instance._is_time_to_sync(
                    instance.last_customer_sync_at,
                    instance.auto_customer_interval_type,
                ):
                    # Customers are derived from orders; re-sync orders.
                    if not report:
                        report = self.env["woo.report"].create({
                            "instance_id": instance.id,
                            "operation": "Auto Sync (Cron)",
                            "status": "running",
                            "message": "Auto sync started",
                            "auto": True,
                            "mode": "cron",
                        })
                    instance.action_sync_orders()
                    instance.last_customer_sync_at = now
                    executed.append("customers")

                if instance.auto_order_sync and instance._is_time_to_sync(
                    instance.last_order_sync_at,
                    instance.auto_order_interval_type,
                ):
                    if not report:
                        report = self.env["woo.report"].create({
                            "instance_id": instance.id,
                            "operation": "Auto Sync (Cron)",
                            "status": "running",
                            "message": "Auto sync started",
                            "auto": True,
                            "mode": "cron",
                        })
                    instance.action_sync_orders()
                    instance.last_order_sync_at = now
                    executed.append("orders")

                if instance.auto_category_sync and instance._is_time_to_sync(
                    instance.last_category_sync_at,
                    instance.auto_category_interval_type,
                ):
                    if not report:
                        report = self.env["woo.report"].create({
                            "instance_id": instance.id,
                            "operation": "Auto Sync (Cron)",
                            "status": "running",
                            "message": "Auto sync started",
                            "auto": True,
                            "mode": "cron",
                        })
                    instance.action_sync_categories()
                    instance.last_category_sync_at = now
                    executed.append("categories")

                if instance.auto_coupon_sync and instance._is_time_to_sync(
                    instance.last_coupon_sync_at,
                    instance.auto_coupon_interval_type,
                ):
                    if not report:
                        report = self.env["woo.report"].create({
                            "instance_id": instance.id,
                            "operation": "Auto Sync (Cron)",
                            "status": "running",
                            "message": "Auto sync started",
                            "auto": True,
                            "mode": "cron",
                        })
                    instance.action_sync_coupons()
                    instance.last_coupon_sync_at = now
                    executed.append("coupons")

                if report:
                    report.write({
                        "status": "success",
                        "message": "Auto sync completed: %s" % ", ".join(executed),
                    })

            except Exception as e:
                _logger.error(
                    "Woo cron auto sync failed for instance %s: %s",
                    instance.name,
                    e,
                )
                if report:
                    report.write({
                        "status": "failed",
                        "message": str(e),
                    })
                else:
                    self.env["woo.report"].create({
                        "instance_id": instance.id,
                        "operation": "Auto Sync (Cron)",
                        "status": "failed",
                        "message": str(e),
                        "auto": True,
                        "mode": "cron",
                    })


