import logging

from odoo import _, api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class WooReport(models.Model):
    _name = "woo.report"
    _description = "Woo Sync Report"
    _order = "run_on desc, id desc"

    instance_id = fields.Many2one(
        "woo.instance",
        string="Woo Instance",
        required=True,
        ondelete="cascade",
    )
    operation = fields.Char(required=True)
    operation_type = fields.Char(string="Operation Type", index=True)
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
    sync_direction = fields.Selection(
        [
            ("import", "Import"),
            ("export", "Export"),
            ("unknown", "Unknown"),
        ],
        string="Sync Direction",
        default="unknown",
        index=True,
    )
    woo_id = fields.Char(string="Woo ID", index=True)
    payload_json = fields.Text(string="Payload JSON")
    error_message = fields.Text(string="Error Message")
    retry_count = fields.Integer(string="Retry Count", default=0)
    last_retry_date = fields.Datetime(string="Last Retry", index=True)
    webhook_log_id = fields.Many2one(
        "woo.webhook.log",
        string="Webhook Log",
        ondelete="set null",
        index=True,
    )

    status = fields.Selection(
        [
            ("pending", "Pending"),
            ("running", "Running"),
            ("success", "Success"),
            ("failed", "Failed"),
            ("ignored", "Ignored"),
            ("cancelled", "Cancelled"),
        ],
        required=True,
        default="running",
        index=True,
    )
    message = fields.Text()
    run_on = fields.Datetime(
        string="Run On",
        default=fields.Datetime.now,
        readonly=True,
        index=True,
    )
    auto = fields.Boolean(default=False)
    line_ids = fields.One2many("woo.report.line", "report_id", string="Details")

    has_webhook = fields.Boolean(
        string="Webhook",
        compute="_compute_has_webhook",
        store=True,
    )
    timeline_count = fields.Integer(
        string="Timeline Count",
        compute="_compute_timeline_count",
    )
    queue_duration_seconds = fields.Float(
        string="Queue Duration (Seconds)",
        compute="_compute_queue_duration",
    )
    queue_duration_display = fields.Char(
        string="Queue Duration",
        compute="_compute_queue_duration",
    )

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        timeline_model = self.env["woo.sync.timeline"].sudo()
        for rec in records:
            try:
                timeline_model.create_from_report(rec, event_reason="create")
            except Exception as exc:
                _logger.warning(
                    "Queue timeline create failed for report %s: %s",
                    rec.id,
                    exc,
                )
        return records

    def write(self, vals):
        tracked_fields = {
            "status",
            "message",
            "error_message",
            "retry_count",
            "last_retry_date",
            "webhook_log_id",
            "woo_id",
            "instance_id",
            "sync_direction",
            "source_action",
            "operation_type",
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
                    "last_retry_date": rec.last_retry_date,
                    "webhook_log_id": rec.webhook_log_id.id if rec.webhook_log_id else False,
                    "woo_id": rec.woo_id,
                    "instance_id": rec.instance_id.id if rec.instance_id else False,
                    "sync_direction": rec.sync_direction,
                    "source_action": rec.source_action,
                    "operation_type": rec.operation_type,
                }
        result = super().write(vals)
        if should_track:
            timeline_model = self.env["woo.sync.timeline"].sudo()
            for rec in self:
                before = before_by_id.get(rec.id, {})
                after = {
                    "status": rec.status,
                    "message": rec.message,
                    "error_message": rec.error_message,
                    "retry_count": rec.retry_count,
                    "last_retry_date": rec.last_retry_date,
                    "webhook_log_id": rec.webhook_log_id.id if rec.webhook_log_id else False,
                    "woo_id": rec.woo_id,
                    "instance_id": rec.instance_id.id if rec.instance_id else False,
                    "sync_direction": rec.sync_direction,
                    "source_action": rec.source_action,
                    "operation_type": rec.operation_type,
                }
                if after != before:
                    try:
                        timeline_model.create_from_report(rec, event_reason="update")
                    except Exception as exc:
                        _logger.warning(
                            "Queue timeline update failed for report %s: %s",
                            rec.id,
                            exc,
                        )
        return result

    @api.depends("mode", "line_ids.source_action", "webhook_log_id")
    def _compute_has_webhook(self):
        for rec in self:
            if rec.mode == "webhook" or rec.webhook_log_id:
                rec.has_webhook = True
            else:
                rec.has_webhook = any(
                    (line.source_action or "") == "webhook" for line in rec.line_ids
                )

    def _compute_timeline_count(self):
        grouped = self.env["woo.sync.timeline"].read_group(
            [("report_id", "in", self.ids)],
            ["report_id"],
            ["report_id"],
        )
        counts = {entry["report_id"][0]: entry["report_id_count"] for entry in grouped}
        for rec in self:
            rec.timeline_count = counts.get(rec.id, 0)

    def _compute_queue_duration(self):
        now = fields.Datetime.now()
        terminal_statuses = {"success", "failed", "ignored", "cancelled"}
        for rec in self:
            start_dt = rec.run_on or rec.create_date
            if not start_dt:
                rec.queue_duration_seconds = 0.0
                rec.queue_duration_display = "00:00:00"
                continue
            end_dt = now
            if rec.status in terminal_statuses:
                end_dt = rec.last_retry_date or rec.write_date or now
            delta_seconds = max((end_dt - start_dt).total_seconds(), 0.0)
            total_seconds = int(delta_seconds)
            hours, remainder = divmod(total_seconds, 3600)
            minutes, seconds = divmod(remainder, 60)
            rec.queue_duration_seconds = delta_seconds
            rec.queue_duration_display = f"{hours:02d}:{minutes:02d}:{seconds:02d}"

    def action_open_related_report(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": _("Queue Report"),
            "res_model": "woo.report",
            "view_mode": "form",
            "res_id": self.id,
            "target": "current",
        }

    def action_open_webhook_log(self):
        self.ensure_one()
        if not self.webhook_log_id:
            raise UserError(_("No webhook log is linked to this queue item."))
        return {
            "type": "ir.actions.act_window",
            "name": _("Webhook Log"),
            "res_model": "woo.webhook.log",
            "view_mode": "form",
            "res_id": self.webhook_log_id.id,
            "target": "current",
        }

    def action_open_related_timeline(self):
        self.ensure_one()
        action = self.env.ref("woo_connector.action_woo_sync_timeline").read()[0]
        action["domain"] = [("report_id", "=", self.id)]
        action["context"] = {"default_report_id": self.id}
        return action

    def action_retry_selected_failed_jobs(self):
        failed_records = self.filtered(lambda rec: rec.status == "failed")
        if not failed_records:
            raise UserError(_("Select failed queue jobs to retry."))

        webhook_records = failed_records.filtered("webhook_log_id")
        generic_records = failed_records - webhook_records
        retried_webhooks = 0
        queued_generic = 0

        for report in webhook_records:
            report.write(
                {
                    "retry_count": report.retry_count + 1,
                    "last_retry_date": fields.Datetime.now(),
                    "status": "running",
                    "message": _("Retrying from queue monitor."),
                }
            )
            report.webhook_log_id.action_retry_webhook()
            retried_webhooks += 1

        if generic_records:
            for report in generic_records:
                report.write(
                    {
                        "retry_count": report.retry_count + 1,
                        "last_retry_date": fields.Datetime.now(),
                        "status": "pending",
                        "message": _("Queued for manual retry from queue monitor."),
                        "error_message": False,
                    }
                )
            queued_generic = len(generic_records)

        message_parts = []
        if retried_webhooks:
            message_parts.append(_("%s webhook job(s) retried") % retried_webhooks)
        if queued_generic:
            message_parts.append(_("%s generic job(s) moved to pending") % queued_generic)

        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("Queue Monitor"),
                "message": ", ".join(message_parts),
                "type": "success",
                "sticky": False,
            },
        }

    def action_cancel_selected_jobs(self):
        cancellable = self.filtered(lambda rec: rec.status in ("pending", "running"))
        if not cancellable:
            raise UserError(_("Select pending or running queue jobs to cancel."))

        cancellable.write(
            {
                "status": "cancelled",
                "message": _("Cancelled from queue monitor."),
            }
        )
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("Queue Monitor"),
                "message": _("%s queue job(s) cancelled.") % len(cancellable),
                "type": "success",
                "sticky": False,
            },
        }
