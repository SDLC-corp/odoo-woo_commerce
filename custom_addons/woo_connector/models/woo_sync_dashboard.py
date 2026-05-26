from datetime import datetime, time, timedelta

from odoo import api, fields, models, _
from odoo.exceptions import UserError


class WooSyncDashboard(models.Model):
    _name = "woo.sync.dashboard"
    _description = "WooCommerce Sync Dashboard"
    _order = "write_date desc, id desc"

    name = fields.Char(default="WooCommerce Dashboard", readonly=True)
    user_id = fields.Many2one(
        "res.users",
        default=lambda self: self.env.user,
        required=True,
        readonly=True,
        ondelete="cascade",
    )
    instance_id = fields.Many2one("woo.instance", string="Woo Instance")
    date_filter = fields.Selection(
        [
            ("today", "Today"),
            ("last_7_days", "Last 7 Days"),
            ("last_30_days", "Last 30 Days"),
            ("custom", "Custom"),
        ],
        string="Date Range",
        default="last_30_days",
        required=True,
    )
    date_from = fields.Datetime(string="Date From")
    date_to = fields.Datetime(string="Date To")

    total_sync_reports = fields.Integer(readonly=True, compute="_compute_dashboard_metrics")
    success_sync_count = fields.Integer(readonly=True, compute="_compute_dashboard_metrics")
    failed_sync_count = fields.Integer(readonly=True, compute="_compute_dashboard_metrics")
    running_sync_count = fields.Integer(readonly=True, compute="_compute_dashboard_metrics")
    pending_queue_count = fields.Integer(readonly=True, compute="_compute_dashboard_metrics")
    running_queue_count = fields.Integer(readonly=True, compute="_compute_dashboard_metrics")
    failed_queue_count = fields.Integer(readonly=True, compute="_compute_dashboard_metrics")
    retried_jobs_today = fields.Integer(readonly=True, compute="_compute_dashboard_metrics")
    webhook_today_count = fields.Integer(readonly=True, compute="_compute_dashboard_metrics")
    failed_webhook_count = fields.Integer(readonly=True, compute="_compute_dashboard_metrics")
    last_health_status = fields.Selection(
        [
            ("not_checked", "Not Checked"),
            ("healthy", "Healthy"),
            ("warning", "Warning"),
            ("failed", "Failed"),
        ],
        readonly=True,
        compute="_compute_dashboard_metrics",
    )
    last_response_time_ms = fields.Float(readonly=True, compute="_compute_dashboard_metrics")
    last_sync_date = fields.Datetime(readonly=True, compute="_compute_dashboard_metrics")
    active_instance_count = fields.Integer(readonly=True, compute="_compute_dashboard_metrics")

    @api.model_create_multi
    def create(self, vals_list):
        if isinstance(vals_list, dict):
            vals_list = [vals_list]
        for vals in vals_list:
            vals.setdefault("user_id", self.env.user.id)
        return super().create(vals_list)

    @api.onchange("date_filter")
    def _onchange_date_filter(self):
        for rec in self:
            today = fields.Date.context_today(rec)
            if rec.date_filter == "today":
                rec.date_from = datetime.combine(today, time.min)
                rec.date_to = datetime.combine(today, time.max)
            elif rec.date_filter == "last_7_days":
                rec.date_from = datetime.combine(today - timedelta(days=6), time.min)
                rec.date_to = datetime.combine(today, time.max)
            elif rec.date_filter == "last_30_days":
                rec.date_from = datetime.combine(today - timedelta(days=29), time.min)
                rec.date_to = datetime.combine(today, time.max)

    @api.constrains("date_filter", "date_from", "date_to")
    def _check_custom_range(self):
        for rec in self:
            if rec.date_filter == "custom" and rec.date_from and rec.date_to and rec.date_from > rec.date_to:
                raise UserError(_("Date From cannot be greater than Date To."))

    def _get_window(self):
        self.ensure_one()
        today = fields.Date.context_today(self)
        if self.date_filter == "today":
            start = datetime.combine(today, time.min)
            end = datetime.combine(today, time.max)
            return start, end
        if self.date_filter == "last_7_days":
            return datetime.combine(today - timedelta(days=6), time.min), datetime.combine(today, time.max)
        if self.date_filter == "last_30_days":
            return datetime.combine(today - timedelta(days=29), time.min), datetime.combine(today, time.max)
        if self.date_filter == "custom" and self.date_from and self.date_to:
            return self.date_from, self.date_to
        return datetime.combine(today - timedelta(days=29), time.min), datetime.combine(today, time.max)

    def _build_domain(self, date_field):
        self.ensure_one()
        domain = []
        if self.instance_id:
            domain.append(("instance_id", "=", self.instance_id.id))
        start, end = self._get_window()
        if start:
            domain.append((date_field, ">=", fields.Datetime.to_string(start)))
        if end:
            domain.append((date_field, "<=", fields.Datetime.to_string(end)))
        return domain

    @api.depends("instance_id", "date_filter", "date_from", "date_to")
    def _compute_dashboard_metrics(self):
        Report = self.env["woo.report"].sudo()
        WebhookLog = self.env["woo.webhook.log"].sudo()
        HealthLog = self.env["woo.connection.health.log"].sudo()
        Instance = self.env["woo.instance"].sudo()

        for rec in self:
            report_domain = rec._build_domain("create_date")
            webhook_domain = rec._build_domain("received_datetime")
            health_domain = [("instance_id", "=", rec.instance_id.id)] if rec.instance_id else []

            rec.total_sync_reports = Report.search_count(report_domain)
            rec.success_sync_count = Report.search_count(report_domain + [("status", "=", "success")])
            rec.failed_sync_count = Report.search_count(report_domain + [("status", "=", "failed")])
            rec.running_sync_count = Report.search_count(report_domain + [("status", "=", "running")])
            rec.pending_queue_count = Report.search_count(report_domain + [("status", "=", "pending")])
            rec.running_queue_count = Report.search_count(report_domain + [("status", "=", "running")])
            rec.failed_queue_count = Report.search_count(report_domain + [("status", "=", "failed")])
            rec.failed_webhook_count = WebhookLog.search_count(webhook_domain + [("status", "=", "failed")])

            today = fields.Date.context_today(rec)
            today_start = datetime.combine(today, time.min)
            today_end = datetime.combine(today, time.max)
            webhook_today_domain = [
                ("received_datetime", ">=", fields.Datetime.to_string(today_start)),
                ("received_datetime", "<=", fields.Datetime.to_string(today_end)),
            ]
            if rec.instance_id:
                webhook_today_domain.append(("instance_id", "=", rec.instance_id.id))
            rec.webhook_today_count = WebhookLog.search_count(webhook_today_domain)
            retried_today_domain = [
                ("retry_count", ">", 0),
                ("last_retry_date", ">=", fields.Datetime.to_string(today_start)),
                ("last_retry_date", "<=", fields.Datetime.to_string(today_end)),
            ]
            if rec.instance_id:
                retried_today_domain.append(("instance_id", "=", rec.instance_id.id))
            rec.retried_jobs_today = Report.search_count(retried_today_domain)

            latest_health = HealthLog.search(health_domain, order="checked_at desc, id desc", limit=1)
            if latest_health:
                rec.last_health_status = "healthy" if latest_health.status == "success" else latest_health.status
            else:
                rec.last_health_status = "not_checked"

            response_domain = [("check_type", "=", "response_time")]
            if rec.instance_id:
                response_domain.append(("instance_id", "=", rec.instance_id.id))
            latest_response = HealthLog.search(response_domain, order="checked_at desc, id desc", limit=1)
            rec.last_response_time_ms = latest_response.response_time_ms if latest_response else 0.0

            latest_sync_domain = [("instance_id", "=", rec.instance_id.id)] if rec.instance_id else []
            latest_sync = Report.search(latest_sync_domain, order="run_on desc, id desc", limit=1)
            rec.last_sync_date = latest_sync.run_on if latest_sync else False

            rec.active_instance_count = Instance.search_count([("active", "=", True)])

    def action_refresh_dashboard(self):
        self.ensure_one()
        return self.action_open_dashboard()

    def action_open_dashboard(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": _("WooCommerce Dashboard"),
            "res_model": "woo.sync.dashboard",
            "view_mode": "form",
            "res_id": self.id,
            "target": "current",
        }

    def action_open_sync_reports(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": _("Sync Reports"),
            "res_model": "woo.report",
            "view_mode": "list,form",
            "domain": self._build_domain("create_date"),
        }

    def action_open_failed_sync_reports(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": _("Failed Sync Reports"),
            "res_model": "woo.report",
            "view_mode": "list,form",
            "domain": self._build_domain("create_date") + [("status", "=", "failed")],
        }

    def action_open_running_sync_reports(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": _("Running Sync Reports"),
            "res_model": "woo.report",
            "view_mode": "list,form",
            "domain": self._build_domain("create_date") + [("status", "=", "running")],
        }

    def action_open_webhook_logs(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": _("Webhook Logs"),
            "res_model": "woo.webhook.log",
            "view_mode": "list,form",
            "domain": self._build_domain("received_datetime"),
        }

    def action_open_failed_webhook_logs(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": _("Failed Webhook Logs"),
            "res_model": "woo.webhook.log",
            "view_mode": "list,form",
            "domain": self._build_domain("received_datetime") + [("status", "=", "failed")],
        }

    def action_open_health_logs(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": _("Connection Health Logs"),
            "res_model": "woo.connection.health.log",
            "view_mode": "list,form",
            "domain": self._build_domain("checked_at"),
        }

    def action_open_instances(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": _("WooCommerce Instances"),
            "res_model": "woo.instance",
            "view_mode": "kanban,list,form",
            "domain": [("active", "=", True)],
        }

    def action_open_queue_monitor(self):
        self.ensure_one()
        action = self.env.ref("woo_connector.action_woo_queue_monitor").read()[0]
        action["domain"] = self._build_domain("create_date")
        return action

    def action_open_queue_pending(self):
        self.ensure_one()
        action = self.action_open_queue_monitor()
        action["name"] = _("Pending Queue Jobs")
        action["domain"] = self._build_domain("create_date") + [("status", "=", "pending")]
        return action

    def action_open_queue_running(self):
        self.ensure_one()
        action = self.action_open_queue_monitor()
        action["name"] = _("Running Queue Jobs")
        action["domain"] = self._build_domain("create_date") + [("status", "=", "running")]
        return action

    def action_open_queue_failed(self):
        self.ensure_one()
        action = self.action_open_queue_monitor()
        action["name"] = _("Failed Queue Jobs")
        action["domain"] = self._build_domain("create_date") + [("status", "=", "failed")]
        return action

    def action_open_retried_today(self):
        self.ensure_one()
        today = fields.Date.context_today(self)
        today_start = datetime.combine(today, time.min)
        today_end = datetime.combine(today, time.max)
        domain = [
            ("retry_count", ">", 0),
            ("last_retry_date", ">=", fields.Datetime.to_string(today_start)),
            ("last_retry_date", "<=", fields.Datetime.to_string(today_end)),
        ]
        if self.instance_id:
            domain.append(("instance_id", "=", self.instance_id.id))
        action = self.action_open_queue_monitor()
        action["name"] = _("Retried Jobs Today")
        action["domain"] = domain
        return action

    def action_open_import_by_id(self):
        self.ensure_one()
        action = self.env.ref("woo_connector.action_woo_import_by_id_wizard").read()[0]
        if self.instance_id:
            action["context"] = dict(self._context, default_instance_id=self.instance_id.id)
        return action

    def action_open_import_by_date_range(self):
        self.ensure_one()
        action = self.env.ref("woo_connector.action_woo_import_date_range_wizard").read()[0]
        if self.instance_id:
            action["context"] = dict(self._context, default_instance_id=self.instance_id.id)
        return action

    def action_run_health_check(self):
        self.ensure_one()
        if not self.instance_id:
            raise UserError(_("Select a Woo Instance to run health check."))
        self.instance_id.action_run_health_check()
        return self.action_open_dashboard()

    @api.model
    def action_open_default_dashboard(self):
        dashboard = self.search([("user_id", "=", self.env.user.id)], order="write_date desc, id desc", limit=1)
        if not dashboard:
            dashboard = self.create({})
            dashboard._onchange_date_filter()
        return {
            "type": "ir.actions.act_window",
            "name": _("WooCommerce Dashboard"),
            "res_model": "woo.sync.dashboard",
            "view_mode": "form",
            "res_id": dashboard.id,
            "target": "current",
        }
