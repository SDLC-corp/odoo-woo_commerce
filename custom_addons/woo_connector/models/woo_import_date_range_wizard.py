import json
import logging
from datetime import datetime

from odoo import _, api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class WooImportDateRangeWizard(models.TransientModel):
    _name = "woo.import.date.range.wizard"
    _description = "Woo Import By Date Range"

    instance_id = fields.Many2one(
        "woo.instance",
        string="Woo Instance",
        required=True,
        default=lambda self: self._default_instance_id(),
    )
    record_type = fields.Selection(
        [
            ("order", "Orders"),
            ("product", "Products"),
            ("customer", "Customers"),
            ("coupon", "Coupons"),
        ],
        required=True,
        default="order",
    )
    date_from = fields.Datetime(string="Date From", required=True)
    date_to = fields.Datetime(string="Date To", required=True)
    date_filter_type = fields.Selection(
        [
            ("created", "Created Date"),
            ("modified", "Modified Date"),
        ],
        required=True,
        default="created",
    )
    page_size = fields.Integer(string="Batch/Page Size", default=50, required=True)
    update_existing = fields.Boolean(
        string="Update existing records",
        default=True,
    )

    def _default_instance_id(self):
        active_model = self.env.context.get("active_model")
        active_id = self.env.context.get("active_id")
        if active_model == "woo.instance" and active_id:
            return active_id
        instance = self.env["woo.instance"].search([("active", "=", True)], limit=1)
        return instance.id if instance else False

    def _validate_inputs(self):
        self.ensure_one()
        if not self.instance_id:
            raise UserError(_("Please select a Woo Instance."))
        if not self.date_from:
            raise UserError(_("Date From is required."))
        if not self.date_to:
            raise UserError(_("Date To is required."))
        if self.date_from > self.date_to:
            raise UserError(_("Date From must not be greater than Date To."))
        if self.page_size <= 0:
            raise UserError(_("Batch/Page Size must be greater than 0."))
        if self.page_size > 100:
            raise UserError(_("Batch/Page Size cannot exceed 100 for WooCommerce API."))
        if self.record_type == "coupon" and "woo.coupon.sync" not in self.env:
            raise UserError(_("Coupon sync model is not available in this module."))

    def _api_endpoint_for_type(self, record_type):
        endpoint_map = {
            "order": "orders",
            "product": "products",
            "customer": "customers",
            "coupon": "coupons",
        }
        endpoint = endpoint_map.get(record_type)
        if not endpoint:
            raise UserError(_("Unsupported record type: %s") % record_type)
        return endpoint

    def _to_woo_iso(self, value):
        if isinstance(value, datetime):
            dt = value
        else:
            dt = fields.Datetime.to_datetime(value)
        if not dt:
            raise UserError(_("Invalid datetime value provided for date range import."))
        return dt.strftime("%Y-%m-%dT%H:%M:%S")

    def _build_date_params(self, page):
        self.ensure_one()
        params = {
            "per_page": self.page_size,
            "page": page,
            "orderby": "date",
            "order": "asc",
        }
        from_iso = self._to_woo_iso(self.date_from)
        to_iso = self._to_woo_iso(self.date_to)
        if self.date_filter_type == "modified":
            params["modified_after"] = from_iso
            params["modified_before"] = to_iso
        else:
            params["after"] = from_iso
            params["before"] = to_iso
        return params

    def _find_existing_record(self, payload):
        self.ensure_one()
        instance = self.instance_id
        woo_id = str(payload.get("id") or "")

        if self.record_type == "product":
            record = self.env["woo.product.sync"].search(
                [
                    ("instance_id", "=", instance.id),
                    ("woo_product_id", "=", woo_id),
                ],
                limit=1,
            )
            if record:
                return record
            if instance.smart_sku_matching:
                sku = instance._normalize_sku(payload.get("sku") or payload.get("slug"))
                if sku:
                    match_info = instance._find_odoo_product_by_sku(sku, instance=instance)
                    return match_info.get("product_tmpl")
            return False

        if self.record_type == "order":
            return self.env["woo.order.sync"].search(
                [
                    ("instance_id", "=", instance.id),
                    ("woo_order_id", "=", woo_id),
                ],
                limit=1,
            )

        if self.record_type == "customer":
            record = self.env["woo.customer.sync"].search(
                [
                    ("instance_id", "=", instance.id),
                    ("woo_customer_id", "=", woo_id),
                ],
                limit=1,
            )
            if record:
                return record
            email = payload.get("email")
            if email:
                return self.env["woo.customer.sync"].search(
                    [
                        ("instance_id", "=", instance.id),
                        ("email", "=", email),
                    ],
                    limit=1,
                )
            return False

        if self.record_type == "coupon":
            record = self.env["woo.coupon.sync"].search(
                [
                    ("instance_id", "=", instance.id),
                    ("woo_coupon_id", "=", woo_id),
                ],
                limit=1,
            )
            if record:
                return record
            code = payload.get("code")
            if code:
                return self.env["woo.coupon.sync"].search(
                    [
                        ("instance_id", "=", instance.id),
                        ("name", "=", code),
                    ],
                    limit=1,
                )
            return False

        return False

    def _sync_single_payload(self, payload, source_action):
        self.ensure_one()
        return self.env["woo.webhook.sync"].sudo().process_single_import(
            record_type=self.record_type,
            payload=payload,
            instance=self.instance_id,
            source_action=source_action,
            log_result=False,
        )

    def _build_summary_payload(self):
        self.ensure_one()
        return {
            "mode": "date_range_import",
            "record_type": self.record_type,
            "endpoint": self._api_endpoint_for_type(self.record_type),
            "date_filter_type": self.date_filter_type,
            "date_from": fields.Datetime.to_string(self.date_from),
            "date_to": fields.Datetime.to_string(self.date_to),
            "page_size": int(self.page_size or 50),
            "update_existing": bool(self.update_existing),
        }

    def _create_parent_report(self, payload_meta, source_action):
        self.ensure_one()
        operation = "Import by Date Range (%s)" % self.record_type.title()
        reference = "%s | %s -> %s" % (
            self.record_type,
            payload_meta.get("date_from"),
            payload_meta.get("date_to"),
        )
        return self.env["woo.report"].create(
            {
                "instance_id": self.instance_id.id,
                "operation": operation,
                "status": "running",
                "message": "Date range import started.",
                "mode": "manual",
                "source_action": source_action,
                "reference": reference,
                "operation_type": self.record_type,
                "sync_direction": "import",
                "payload_json": json.dumps(payload_meta, default=str),
            }
        )

    def _run_import(self, source_action="date_range_import"):
        self.ensure_one()
        self._validate_inputs()
        payload_meta = self._build_summary_payload()
        parent_report = self._create_parent_report(payload_meta, source_action)

        endpoint = self._api_endpoint_for_type(self.record_type)
        wcapi = self.instance_id._get_wcapi(self.instance_id)

        total_fetched = 0
        success_count = 0
        failed_count = 0
        skipped_count = 0
        sku_linked_count = 0
        page = 1

        try:
            while True:
                params = self._build_date_params(page)
                response = wcapi.get(endpoint, params=params)
                if response.status_code != 200:
                    raise UserError(
                        _(
                            "Failed to fetch %s from WooCommerce.\n"
                            "Status: %s\nResponse: %s"
                        )
                        % (self.record_type, response.status_code, response.text)
                    )

                batch = response.json()
                if not isinstance(batch, list):
                    raise UserError(
                        _("Unexpected WooCommerce response format for %s date range import.")
                        % self.record_type
                    )

                if not batch:
                    break

                total_fetched += len(batch)

                for item in batch:
                    if not isinstance(item, dict):
                        failed_count += 1
                        self.env["woo.report.line"].create(
                            {
                                "report_id": parent_report.id,
                                "record_type": self.record_type,
                                "source_action": source_action,
                                "woo_id": False,
                                "name": "Invalid payload item",
                                "status": "error",
                                "error_message": "Payload item is not an object/dict.",
                            }
                        )
                        continue

                    woo_id = str(item.get("id") or "")
                    try:
                        existing = self._find_existing_record(item)
                        if existing and not self.update_existing:
                            skipped_count += 1
                            continue

                        sync_result = self._sync_single_payload(item, source_action=source_action)
                        success_count += 1
                        if self.record_type == "product" and (sync_result or {}).get("matched_by") == "sku":
                            sku_linked_count += 1
                            self.env["woo.report.line"].create(
                                {
                                    "report_id": parent_report.id,
                                    "record_type": self.record_type,
                                    "source_action": source_action,
                                    "woo_id": woo_id or False,
                                    "name": (sync_result or {}).get("message"),
                                    "status": "success",
                                    "error_message": False,
                                }
                            )
                    except Exception as exc:
                        failed_count += 1
                        self.env["woo.report.line"].create(
                            {
                                "report_id": parent_report.id,
                                "record_type": self.record_type,
                                "source_action": source_action,
                                "woo_id": woo_id or False,
                                "name": str(item.get("name") or item.get("number") or woo_id or "Unknown"),
                                "status": "error",
                                "error_message": str(exc),
                            }
                        )

                if len(batch) < self.page_size:
                    break
                page += 1

            status = "success" if failed_count == 0 else "failed"
            summary_message = _(
                "Date range import finished. "
                "Fetched: %(fetched)s, Success: %(success)s, Failed: %(failed)s, "
                "Skipped: %(skipped)s, SKU linked: %(sku_linked)s."
            ) % {
                "fetched": total_fetched,
                "success": success_count,
                "failed": failed_count,
                "skipped": skipped_count,
                "sku_linked": sku_linked_count,
            }

            parent_report.write(
                {
                    "status": status,
                    "message": summary_message,
                    "error_message": summary_message if status == "failed" else False,
                }
            )

            return {
                "status": status,
                "message": summary_message,
                "total_fetched": total_fetched,
                "success_count": success_count,
                "failed_count": failed_count,
                "skipped_count": skipped_count,
                "sku_linked_count": sku_linked_count,
            }
        except Exception as exc:
            error_message = str(exc)
            _logger.exception("Date range import failed for %s", self.record_type)
            parent_report.write(
                {
                    "status": "failed",
                    "message": error_message,
                    "error_message": error_message,
                }
            )
            raise UserError(error_message)

    @api.model
    def run_from_payload(self, instance, payload_data):
        if not instance:
            raise UserError(_("Woo instance is missing for retry."))
        data = payload_data if isinstance(payload_data, dict) else {}
        update_existing = data.get("update_existing", True)
        if isinstance(update_existing, str):
            update_existing = update_existing.strip().lower() in ("1", "true", "yes", "y")
        wizard = self.create(
            {
                "instance_id": instance.id,
                "record_type": data.get("record_type"),
                "date_from": data.get("date_from"),
                "date_to": data.get("date_to"),
                "date_filter_type": data.get("date_filter_type") or "created",
                "page_size": int(data.get("page_size") or 50),
                "update_existing": bool(update_existing),
            }
        )
        return wizard._run_import(source_action="date_range_import")

    def action_import_date_range(self):
        self.ensure_one()
        summary = self._run_import(source_action="date_range_import")
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("Import by Date Range"),
                "message": summary["message"],
                "type": "success" if summary["status"] == "success" else "warning",
                "sticky": summary["status"] != "success",
            },
        }

    def action_preview_sync(self):
        self.ensure_one()
        self._validate_inputs()
        preview = self.env["woo.sync.preview"].create_and_run_preview(
            {
                "name": _("Preview - Date Range Import"),
                "source_mode": "date_range",
                "instance_id": self.instance_id.id,
                "record_type": self.record_type,
                "date_filter_type": self.date_filter_type,
                "date_from": self.date_from,
                "date_to": self.date_to,
                "page_size": self.page_size,
                "update_existing": self.update_existing,
            }
        )
        return preview.action_open_preview()
