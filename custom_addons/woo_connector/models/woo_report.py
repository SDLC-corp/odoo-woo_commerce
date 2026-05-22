import json
import logging

from odoo import api, fields, models
from odoo import _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class WooReport(models.Model):
    _name = "woo.report"
    _description = "Woo Sync Report"
    _order = "run_on desc"

    instance_id = fields.Many2one(
        "woo.instance",
        string="Woo Instance",
        required=True,
        ondelete="cascade",
    )

    operation = fields.Char(required=True)

    mode = fields.Selection(
        [
            ("manual", "Manual"),
            ("cron", "Cron"),
            ("webhook", "Webhook"),
        ],
        string="Mode",
        default="manual",
        index=True,
    )

    source_action = fields.Char(string="Source Action")
    reference = fields.Char(string="Woo Reference ID", index=True)

    status = fields.Selection(
        [
            ("running", "Running"),
            ("success", "Success"),
            ("failed", "Failed"),
            ("ignored", "Ignored"),
        ],
        required=True,
        default="running",
    )
    message = fields.Text()
    error_message = fields.Text(string="Latest Error")
    run_on = fields.Datetime(
        string="Run On",
        default=fields.Datetime.now,
        readonly=True,
    )
    auto = fields.Boolean(default=False)
    retry_count = fields.Integer(default=0, readonly=True)
    last_retry_date = fields.Datetime(readonly=True)
    operation_type = fields.Char(index=True)
    sync_direction = fields.Selection(
        [
            ("import", "Import"),
            ("export", "Export"),
            ("unknown", "Unknown"),
        ],
        default="unknown",
        required=True,
    )
    woo_id = fields.Char(string="Woo ID", index=True)
    payload_json = fields.Text(string="Payload JSON")
    ai_explanation = fields.Text(string="AI Explanation", readonly=True)
    ai_suggested_fix = fields.Text(string="AI Suggested Fix", readonly=True)
    ai_retry_recommended = fields.Boolean(string="AI Retry Recommended", readonly=True)
    ai_last_analyzed_at = fields.Datetime(string="AI Last Analyzed At", readonly=True)
    webhook_log_id = fields.Many2one(
        "woo.webhook.log",
        string="Webhook Log",
        ondelete="set null",
        index=True,
    )

    webhook_log_count = fields.Integer(compute="_compute_webhook_log_count")
    timeline_count = fields.Integer(compute="_compute_timeline_count")
    queue_duration_seconds = fields.Float(
        string="Duration (s)",
        compute="_compute_queue_duration",
    )
    queue_duration_display = fields.Char(
        string="Duration",
        compute="_compute_queue_duration",
    )

    line_ids = fields.One2many(
        "woo.report.line",
        "report_id",
        string="Details",
    )

    has_webhook = fields.Boolean(
        string="Webhook",
        compute="_compute_has_webhook",
        store=True,
    )

    @api.depends("mode", "line_ids.source_action")
    def _compute_has_webhook(self):
        for rec in self:
            if rec.mode == "webhook":
                rec.has_webhook = True
            else:
                rec.has_webhook = any(
                    (line.source_action or "") == "webhook" for line in rec.line_ids
                )

    @api.depends("webhook_log_id")
    def _compute_webhook_log_count(self):
        for rec in self:
            rec.webhook_log_count = 1 if rec.webhook_log_id else 0

    @api.depends("create_date", "write_date", "status")
    def _compute_queue_duration(self):
        now_dt = fields.Datetime.now()
        for rec in self:
            start = rec.create_date or rec.run_on
            if not start:
                rec.queue_duration_seconds = 0.0
                rec.queue_duration_display = "00:00:00"
                continue
            end = now_dt if rec.status == "running" else (rec.write_date or now_dt)
            delta = end - start
            seconds = max(delta.total_seconds(), 0.0)
            rec.queue_duration_seconds = seconds
            hours = int(seconds // 3600)
            minutes = int((seconds % 3600) // 60)
            secs = int(seconds % 60)
            rec.queue_duration_display = f"{hours:02d}:{minutes:02d}:{secs:02d}"

    def _compute_timeline_count(self):
        grouped = self.env["woo.sync.timeline"].read_group(
            [("report_id", "in", self.ids)],
            ["report_id"],
            ["report_id"],
        )
        counts = {entry["report_id"][0]: entry["report_id_count"] for entry in grouped}
        for rec in self:
            rec.timeline_count = counts.get(rec.id, 0)

    def action_open_webhook_log(self):
        self.ensure_one()
        if not self.webhook_log_id:
            return False
        return {
            "type": "ir.actions.act_window",
            "name": "Webhook Log",
            "res_model": "woo.webhook.log",
            "view_mode": "form",
            "res_id": self.webhook_log_id.id,
            "target": "current",
        }

    def action_open_related_report(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": _("Queue Job"),
            "res_model": "woo.report",
            "view_mode": "form",
            "res_id": self.id,
            "target": "current",
        }

    def action_open_related_timeline(self):
        self.ensure_one()
        action = self.env.ref("woo_connector.action_woo_sync_timeline").read()[0]
        action["domain"] = [("report_id", "=", self.id)]
        action["context"] = {"default_report_id": self.id}
        return action

    @api.model_create_multi
    def create(self, vals_list):
        enriched_vals_list = []
        for vals in vals_list:
            data = dict(vals)
            operation = data.get("operation") or ""
            source_action = data.get("source_action") or ""
            mode = data.get("mode") or ""
            if not data.get("operation_type"):
                data["operation_type"] = self._infer_operation_type(
                    operation,
                    source_action,
                )
            if not data.get("sync_direction"):
                data["sync_direction"] = self._infer_sync_direction(
                    operation,
                    source_action,
                    mode,
                )
            if not data.get("woo_id") and data.get("reference"):
                data["woo_id"] = data.get("reference")
            if data.get("status") == "failed" and not data.get("error_message"):
                data["error_message"] = data.get("message") or ""
            enriched_vals_list.append(data)
        reports = super().create(enriched_vals_list)
        timeline_model = self.env["woo.sync.timeline"].sudo()
        for report in reports:
            timeline_model.create_from_report(report, event_reason="create")
        return reports

    def write(self, vals):
        tracked_fields = {
            "status",
            "message",
            "error_message",
            "retry_count",
            "last_retry_date",
            "source_action",
            "sync_direction",
            "operation_type",
            "woo_id",
            "webhook_log_id",
        }
        should_track = any(field_name in vals for field_name in tracked_fields)
        before_by_id = {}
        if should_track:
            for rec in self:
                before_by_id[rec.id] = {
                    "status": rec.status,
                    "message": rec.message,
                    "error_message": rec.error_message,
                    "retry_count": rec.retry_count,
                    "webhook_log_id": rec.webhook_log_id.id if rec.webhook_log_id else False,
                }

        result = super().write(vals)

        if should_track:
            timeline_model = self.env["woo.sync.timeline"].sudo()
            for rec in self:
                before = before_by_id.get(rec.id, {})
                if (
                    rec.status != before.get("status")
                    or rec.message != before.get("message")
                    or rec.error_message != before.get("error_message")
                    or rec.retry_count != before.get("retry_count")
                    or (rec.webhook_log_id.id if rec.webhook_log_id else False) != before.get("webhook_log_id")
                ):
                    timeline_model.create_from_report(rec, event_reason="update")
        return result

    @api.model
    def _infer_operation_type(self, operation, source_action):
        text = f"{operation or ''} {source_action or ''}".lower()
        if "product" in text:
            return "product"
        if "order" in text:
            return "order"
        if "customer" in text:
            return "customer"
        if "category" in text:
            return "category"
        if "coupon" in text or "giftcard" in text:
            return "coupon"
        if "stock" in text or "inventory" in text:
            return "stock"
        if "refund" in text:
            return "refund"
        if "analytic" in text or "report" in text:
            return "analytics"
        if "auto" in text:
            return "auto"
        if "signature" in text:
            return "signature"
        return "unknown"

    @api.model
    def _infer_sync_direction(self, operation, source_action, mode):
        text = f"{operation or ''} {source_action or ''} {mode or ''}".lower()
        if any(tag in text for tag in ("push", "export", "to woo", "to woocommerce")):
            return "export"
        if any(tag in text for tag in ("pull", "import", "sync", "webhook", "cron", "auto")):
            return "import"
        return "unknown"

    def _payload_to_dict(self):
        self.ensure_one()
        if not self.payload_json:
            return {}
        try:
            data = json.loads(self.payload_json)
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}

    def _fetch_payload_from_woo(self, operation_type, woo_id):
        self.ensure_one()
        endpoint_map = {
            "product": "products",
            "order": "orders",
            "customer": "customers",
            "category": "products/categories",
            "coupon": "coupons",
        }
        endpoint = endpoint_map.get(operation_type)
        if not endpoint or not woo_id:
            return {}

        wcapi = self.instance_id._get_wcapi(self.instance_id)
        response = wcapi.get(f"{endpoint}/{woo_id}")
        if response.status_code != 200:
            raise ValueError(response.text)
        payload = response.json()
        return payload if isinstance(payload, dict) else {}

    def _retry_webhook_operation(self, operation_type):
        self.ensure_one()
        payload = self._payload_to_dict()
        if not payload:
            payload = self._fetch_payload_from_woo(
                operation_type,
                self.woo_id or self.reference,
            )
        if not payload:
            raise ValueError("Retry payload is not available for this webhook log.")

        sync_service = self.env["woo.webhook.sync"].sudo()
        sync_service.process_single_import(
            record_type=operation_type,
            payload=payload,
            instance=self.instance_id,
            source_action=self.source_action or "retry_sync",
            log_result=False,
        )
        return f"Retry succeeded for webhook {operation_type}."

    def _retry_date_range_operation(self):
        self.ensure_one()
        payload = self._payload_to_dict()
        if not payload:
            raise ValueError("Date range retry payload is missing.")
        summary = self.env["woo.import.date.range.wizard"].sudo().run_from_payload(
            self.instance_id,
            payload,
        )
        return summary.get("message") or "Date range retry completed."

    def _retry_manual_record_sync_operation(self):
        self.ensure_one()
        payload = self._payload_to_dict()
        target_model = payload.get("target_model")
        target_id = payload.get("target_id")
        sync_direction = payload.get("sync_direction") or self.sync_direction
        if not target_model or not target_id:
            raise ValueError("Manual record sync retry target metadata is missing.")

        record = self.env[target_model].browse(int(target_id)).exists()
        if not record:
            raise ValueError("Manual record sync retry target record does not exist.")

        if sync_direction == "export":
            callback = "action_manual_export_to_woo"
        else:
            callback = "action_manual_import_from_woo"

        if not hasattr(record, callback):
            raise ValueError(
                f"Manual record sync retry callback '{callback}' is not available on model '{target_model}'."
            )

        result = getattr(record, callback)(instance=self.instance_id, via_wizard=True)
        if isinstance(result, dict):
            params = result.get("params") if isinstance(result.get("params"), dict) else {}
            return params.get("message") or result.get("message") or f"Retry succeeded for {self.operation}."
        return f"Retry succeeded for {self.operation}."

    def _retry_full_operation(self, operation_type):
        self.ensure_one()
        retry_map = {
            "product": self.instance_id.action_sync_products,
            "order": self.instance_id.action_sync_orders,
            "customer": self.instance_id.action_sync_customers,
            "category": self.instance_id.action_sync_categories,
            "coupon": self.instance_id.action_sync_coupons,
            "analytics": self.instance_id.action_sync_reports,
            "auto": lambda: self.instance_id.auto_sync_all(force=True),
            "stock": self.instance_id.action_sync_products,
            "refund": self.instance_id.action_sync_orders,
        }
        retry_callable = retry_map.get(operation_type)
        if not retry_callable:
            raise ValueError(
                f"Unsupported retry operation '{self.operation}' "
                f"(type: {operation_type})."
            )
        retry_callable()
        return f"Retry succeeded for {self.operation}."

    def _retry_single_report(self):
        self.ensure_one()
        if self.status != "failed":
            return False, "Retry is allowed only for failed logs."

        operation_type = self.operation_type or self._infer_operation_type(
            self.operation,
            self.source_action,
        )
        sync_direction = self.sync_direction or self._infer_sync_direction(
            self.operation,
            self.source_action,
            self.mode,
        )
        woo_id = self.woo_id or self.reference or False

        self.write(
            {
                "operation_type": operation_type,
                "sync_direction": sync_direction,
                "woo_id": woo_id,
                "retry_count": self.retry_count + 1,
                "last_retry_date": fields.Datetime.now(),
            }
        )

        try:
            is_date_range_retry = (self.source_action or "") == "date_range_import"
            is_manual_record_retry = (self.source_action or "") == "manual_record_sync"
            is_single_payload_retry = (
                self.mode == "webhook"
                or "webhook" in (self.operation or "").lower()
                or (self.source_action or "") == "manual_import_by_id"
                or (self.source_action or "") == "manual_record_sync"
            )
            if is_date_range_retry:
                success_message = self._retry_date_range_operation()
            elif is_manual_record_retry:
                success_message = self._retry_manual_record_sync_operation()
            elif is_single_payload_retry:
                success_message = self._retry_webhook_operation(operation_type)
            else:
                success_message = self._retry_full_operation(operation_type)

            self.write(
                {
                    "status": "success",
                    "message": success_message,
                    "error_message": False,
                }
            )
            return True, success_message
        except Exception as exc:
            error_message = str(exc)
            _logger.exception("Retry failed for Woo report %s", self.id)
            self.write(
                {
                    "status": "failed",
                    "message": error_message,
                    "error_message": error_message,
                }
            )
            return False, error_message

    def action_retry_sync(self):
        failed_records = self.filtered(lambda rec: rec.status == "failed")
        if not failed_records:
            return {
                "type": "ir.actions.client",
                "tag": "display_notification",
                "params": {
                    "title": "Retry Sync",
                    "message": "Select a failed sync log to retry.",
                    "type": "warning",
                },
            }

        success_count = 0
        failed_count = 0
        last_error = ""
        for rec in failed_records:
            ok, msg = rec._retry_single_report()
            if ok:
                success_count += 1
            else:
                failed_count += 1
                last_error = msg

        notification_type = "success" if failed_count == 0 else "warning"
        message = f"Retry complete: {success_count} succeeded, {failed_count} failed."
        if failed_count and len(failed_records) == 1 and last_error:
            message = f"{message}\n{last_error}"

        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": "Retry Sync",
                "message": message,
                "type": notification_type,
                "sticky": failed_count > 0,
            },
        }

    def action_retry_selected_failed_jobs(self):
        failed_records = self.filtered(lambda rec: rec.status == "failed")
        skipped_records = self - failed_records
        if not failed_records:
            message = _("No failed jobs selected for retry.")
            if skipped_records:
                message = _("%(msg)s Skipped non-failed: %(count)s.") % {
                    "msg": message,
                    "count": len(skipped_records),
                }
            return {
                "type": "ir.actions.client",
                "tag": "display_notification",
                "params": {
                    "title": _("Queue Monitor"),
                    "message": message,
                    "type": "warning",
                },
            }

        success_count = 0
        failed_count = 0
        for rec in failed_records:
            ok, _msg = rec._retry_single_report()
            if ok:
                success_count += 1
            else:
                failed_count += 1

        message = _(
            "Batch retry complete. Success: %(success)s | Failed: %(failed)s | Skipped non-failed: %(skipped)s."
        ) % {
            "success": success_count,
            "failed": failed_count,
            "skipped": len(skipped_records),
        }
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("Queue Monitor"),
                "message": message,
                "type": "success" if failed_count == 0 else "warning",
                "sticky": failed_count > 0,
            },
        }

    def action_cancel_selected_jobs(self):
        cancellable = self.filtered(lambda rec: rec.status in ("pending", "running"))
        if not cancellable:
            return {
                "type": "ir.actions.client",
                "tag": "display_notification",
                "params": {
                    "title": _("Queue Monitor"),
                    "message": _(
                        "No pending/running jobs can be cancelled. "
                        "Current queue uses statuses: running/success/failed/ignored."
                    ),
                    "type": "warning",
                },
            }

        now_text = fields.Datetime.to_string(fields.Datetime.now())
        for rec in cancellable:
            rec.write(
                {
                    "status": "ignored",
                    "message": _(
                        "Cancelled from Queue Monitor at %s. Underlying worker cancellation is not forced."
                    ) % now_text,
                }
            )
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("Queue Monitor"),
                "message": _("Cancelled/marked ignored jobs: %s") % len(cancellable),
                "type": "success",
            },
        }

    def action_explain_error_with_ai(self):
        failed_records = self.filtered(lambda rec: rec.status == "failed")
        if not failed_records:
            return {
                "type": "ir.actions.client",
                "tag": "display_notification",
                "params": {
                    "title": _("AI Error Assistant"),
                    "message": _("Select failed sync report(s) to analyze."),
                    "type": "warning",
                },
            }

        assistant = self.env["woo.ai.error.assistant"].sudo()
        analyzed_count = 0
        failed_count = 0
        for rec in failed_records:
            try:
                result = assistant.explain_report_error(rec)
                rec.write(result)
                analyzed_count += 1
            except UserError:
                raise
            except Exception:
                failed_count += 1
                safe_error = _("AI analysis request failed. Verify AI configuration and provider availability.")
                rec.write(
                    {
                        "ai_explanation": safe_error,
                        "ai_suggested_fix": _("Re-check endpoint, model, and key; then try again."),
                        "ai_retry_recommended": False,
                        "ai_last_analyzed_at": fields.Datetime.now(),
                    }
                )

        msg = _("AI analysis complete. Success: %(ok)s | Failed: %(fail)s.") % {
            "ok": analyzed_count,
            "fail": failed_count,
        }
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("AI Error Assistant"),
                "message": msg,
                "type": "success" if failed_count == 0 else "warning",
                "sticky": failed_count > 0,
            },
        }

