import json

from odoo import api, fields, models


class WooSyncTimeline(models.Model):
    _name = "woo.sync.timeline"
    _description = "Woo Sync Timeline"
    _order = "event_datetime desc, id desc"

    EVENT_TYPE_SELECTION = [
        ("sync", "Sync"),
        ("manual", "Manual Sync"),
        ("retry", "Retry"),
        ("webhook", "Webhook"),
        ("auto_mapping", "Auto Mapping"),
    ]

    STATUS_SELECTION = [
        ("running", "Running"),
        ("received", "Received"),
        ("success", "Success"),
        ("failed", "Failed"),
        ("ignored", "Ignored"),
    ]

    model_name = fields.Char(index=True)
    res_id = fields.Integer(index=True)
    operation_type = fields.Char(index=True)
    sync_direction = fields.Selection(
        [
            ("import", "Import"),
            ("export", "Export"),
            ("unknown", "Unknown"),
        ],
        default="unknown",
        required=True,
        index=True,
    )
    source_action = fields.Char(index=True)
    status = fields.Selection(STATUS_SELECTION, required=True, index=True)
    event_type = fields.Selection(EVENT_TYPE_SELECTION, default="sync", required=True, index=True)
    woo_id = fields.Char(index=True)
    message = fields.Text()
    event_datetime = fields.Datetime(required=True, index=True, default=fields.Datetime.now)
    event_key = fields.Char(index=True)

    instance_id = fields.Many2one("woo.instance", string="Woo Instance", ondelete="set null", index=True)
    report_id = fields.Many2one("woo.report", string="Sync Report", ondelete="set null", index=True)
    webhook_log_id = fields.Many2one("woo.webhook.log", string="Webhook Log", ondelete="set null", index=True)

    product_tmpl_id = fields.Many2one("product.template", ondelete="cascade", index=True)
    sale_order_id = fields.Many2one("sale.order", ondelete="cascade", index=True)
    partner_id = fields.Many2one("res.partner", ondelete="cascade", index=True)
    category_id = fields.Many2one("product.category", ondelete="cascade", index=True)
    coupon_sync_id = fields.Many2one("woo.coupon.sync", ondelete="cascade", index=True)

    @api.model
    def _json_to_dict(self, value):
        if not value:
            return {}
        if isinstance(value, dict):
            return value
        try:
            payload = json.loads(value)
            return payload if isinstance(payload, dict) else {}
        except Exception:
            return {}

    @api.model
    def _extract_woo_id(self, payload):
        if not isinstance(payload, dict):
            return False
        for key in ("woo_id", "id", "order_id", "product_id", "customer_id", "coupon_id"):
            if payload.get(key):
                return str(payload.get(key))
        nested_payload = payload.get("payload")
        if isinstance(nested_payload, dict):
            return self._extract_woo_id(nested_payload)
        return False

    @api.model
    def _resolve_business_record(self, operation_type=None, woo_id=None, instance_id=None, payload=None):
        payload = payload if isinstance(payload, dict) else {}
        operation = (operation_type or "").lower()
        resolved_woo_id = str(woo_id or self._extract_woo_id(payload) or "").strip()
        instance = self.env["woo.instance"].browse(instance_id).exists() if instance_id else False

        if operation == "product":
            domain = [("woo_product_id", "=", resolved_woo_id)]
            if "woo_instance_id" in self.env["product.template"]._fields and instance:
                domain.append(("woo_instance_id", "in", [False, instance.id]))
            product = self.env["product.template"].sudo().search(domain, order="id desc", limit=1)
            if product:
                return "product.template", product.id

        if operation == "order":
            domain = [("woo_order_id", "=", resolved_woo_id)]
            if "woo_instance_id" in self.env["sale.order"]._fields and instance:
                domain.append(("woo_instance_id", "in", [False, instance.id]))
            order = self.env["sale.order"].sudo().search(domain, order="id desc", limit=1)
            if order:
                return "sale.order", order.id

        if operation == "customer":
            domain = [("woo_customer_id", "=", resolved_woo_id)]
            if "woo_instance_id" in self.env["res.partner"]._fields and instance:
                domain.append(("woo_instance_id", "in", [False, instance.id]))
            partner = self.env["res.partner"].sudo().search(domain, order="id desc", limit=1)
            if not partner and payload.get("email"):
                domain = [("email", "=", payload.get("email"))]
                if "woo_instance_id" in self.env["res.partner"]._fields and instance:
                    domain.append(("woo_instance_id", "in", [False, instance.id]))
                partner = self.env["res.partner"].sudo().search(domain, order="id desc", limit=1)
            if partner:
                return "res.partner", partner.id

        if operation == "category":
            domain = [("woo_category_id", "=", resolved_woo_id)]
            if "woo_instance_id" in self.env["product.category"]._fields and instance:
                domain.append(("woo_instance_id", "in", [False, instance.id]))
            category = self.env["product.category"].sudo().search(domain, order="id desc", limit=1)
            if not category and payload.get("name"):
                category = self.env["product.category"].sudo().search(
                    [("name", "=", payload.get("name"))], order="id desc", limit=1
                )
            if category:
                return "product.category", category.id

        if operation == "coupon":
            domain = [("woo_coupon_id", "=", resolved_woo_id)]
            if instance:
                domain.append(("instance_id", "=", instance.id))
            coupon = self.env["woo.coupon.sync"].sudo().search(domain, order="id desc", limit=1)
            if not coupon:
                code = payload.get("code") or payload.get("name")
                if code:
                    domain = [("name", "=", code)]
                    if instance:
                        domain.append(("instance_id", "=", instance.id))
                    coupon = self.env["woo.coupon.sync"].sudo().search(domain, order="id desc", limit=1)
            if coupon:
                return "woo.coupon.sync", coupon.id

        if operation == "auto_mapping":
            category_name = payload.get("name")
            category_woo_id = str(payload.get("id") or "").strip()
            if category_name or category_woo_id:
                domain = []
                if category_woo_id:
                    domain.append(("woo_category_id", "=", category_woo_id))
                elif category_name:
                    domain.append(("name", "=", category_name))
                if "woo_instance_id" in self.env["product.category"]._fields and instance:
                    domain.append(("woo_instance_id", "in", [False, instance.id]))
                category = self.env["product.category"].sudo().search(domain, order="id desc", limit=1)
                if category:
                    return "product.category", category.id

        return False, False

    @api.model
    def _target_field_values(self, model_name, res_id):
        values = {
            "model_name": model_name or False,
            "res_id": int(res_id) if res_id else False,
        }
        mapping = {
            "product.template": "product_tmpl_id",
            "sale.order": "sale_order_id",
            "res.partner": "partner_id",
            "product.category": "category_id",
            "woo.coupon.sync": "coupon_sync_id",
        }
        for field_name in mapping.values():
            values[field_name] = False
        target_field = mapping.get(model_name)
        if target_field and res_id:
            values[target_field] = int(res_id)
        return values

    @api.model
    def _build_event_key(self, event_type, status, source_action, sync_direction, model_name, res_id, report_id, webhook_log_id, retry_count, marker):
        return "|".join(
            [
                event_type or "",
                status or "",
                source_action or "",
                sync_direction or "",
                model_name or "",
                str(res_id or 0),
                str(report_id or 0),
                str(webhook_log_id or 0),
                str(retry_count or 0),
                marker or "",
            ]
        )

    @api.model
    def _create_timeline_event(self, values):
        event_key = values.get("event_key")
        if event_key:
            existing = self.search([("event_key", "=", event_key)], limit=1)
            if existing:
                return existing
        return self.create(values)

    @api.model
    def _detect_event_type(self, source_action, mode, retry_count=0):
        source = (source_action or "").lower()
        if "webhook" in source or mode == "webhook":
            return "webhook"
        if "retry" in source or retry_count:
            return "retry"
        if source in ("manual_record_sync", "manual_import_by_id", "date_range_import"):
            return "manual"
        if source == "auto_mapping":
            return "auto_mapping"
        return "sync"

    @api.model
    def create_from_report(self, report, event_reason="create"):
        payload = self._json_to_dict(report.payload_json)
        source_action = report.source_action or report.mode or "sync"
        event_type = self._detect_event_type(source_action, report.mode, retry_count=report.retry_count if event_reason == "update" else 0)
        status = report.status or "success"
        woo_id = str(report.woo_id or report.reference or self._extract_woo_id(payload) or "").strip() or False

        target_model = payload.get("target_model")
        target_id = payload.get("target_id")
        if target_model and target_id:
            target_record = self.env[target_model].sudo().browse(int(target_id)).exists()
            if not target_record:
                target_model, target_id = False, False
        if not target_model or not target_id:
            target_model, target_id = self._resolve_business_record(
                operation_type=report.operation_type,
                woo_id=woo_id,
                instance_id=report.instance_id.id if report.instance_id else False,
                payload=payload,
            )

        marker = event_reason
        if event_type == "retry":
            marker = f"{marker}:{report.last_retry_date or report.write_date or ''}"
        elif status in ("running", "received"):
            marker = f"{marker}:{report.run_on or report.create_date or ''}"
        else:
            marker = f"{marker}:{report.write_date or report.run_on or ''}"

        values = {
            **self._target_field_values(target_model, target_id),
            "operation_type": report.operation_type or "unknown",
            "sync_direction": report.sync_direction or "unknown",
            "source_action": source_action,
            "status": status,
            "event_type": event_type,
            "woo_id": woo_id,
            "instance_id": report.instance_id.id if report.instance_id else False,
            "report_id": report.id,
            "webhook_log_id": report.webhook_log_id.id if report.webhook_log_id else False,
            "message": report.error_message if status == "failed" and report.error_message else (report.message or report.operation),
            "event_datetime": report.last_retry_date or report.run_on or fields.Datetime.now(),
        }
        values["event_key"] = self._build_event_key(
            values["event_type"],
            values["status"],
            values["source_action"],
            values["sync_direction"],
            values["model_name"],
            values["res_id"],
            values["report_id"],
            values["webhook_log_id"],
            report.retry_count if event_type == "retry" else 0,
            marker,
        )
        return self._create_timeline_event(values)

    @api.model
    def create_from_webhook_log(self, webhook_log, event_reason="create"):
        payload = self._json_to_dict(webhook_log.payload_json)
        operation_type = webhook_log.resource_type or "unknown"
        woo_id = str(webhook_log.woo_id or self._extract_woo_id(payload) or "").strip() or False
        source_action = webhook_log.source_action or "webhook"
        status = webhook_log.status or "received"
        target_model, target_id = self._resolve_business_record(
            operation_type=operation_type,
            woo_id=woo_id,
            instance_id=webhook_log.instance_id.id if webhook_log.instance_id else False,
            payload=payload,
        )
        report = webhook_log.related_report_id
        if not report and webhook_log.webhook_report_ids:
            report = webhook_log.webhook_report_ids.sorted(lambda r: r.id, reverse=True)[:1]
        event_datetime = webhook_log.processed_datetime or webhook_log.received_datetime or fields.Datetime.now()
        marker = f"{event_reason}:{webhook_log.processed_datetime or webhook_log.write_date or ''}"

        values = {
            **self._target_field_values(target_model, target_id),
            "operation_type": operation_type,
            "sync_direction": "import",
            "source_action": source_action,
            "status": status,
            "event_type": "webhook",
            "woo_id": woo_id,
            "instance_id": webhook_log.instance_id.id if webhook_log.instance_id else False,
            "report_id": report.id if report else False,
            "webhook_log_id": webhook_log.id,
            "message": webhook_log.error_message or webhook_log.topic or webhook_log.event or "Webhook event",
            "event_datetime": event_datetime,
        }
        values["event_key"] = self._build_event_key(
            values["event_type"],
            values["status"],
            values["source_action"],
            values["sync_direction"],
            values["model_name"],
            values["res_id"],
            values["report_id"],
            values["webhook_log_id"],
            webhook_log.retry_count,
            marker,
        )
        return self._create_timeline_event(values)

    def action_open_source_document(self):
        self.ensure_one()
        if self.report_id:
            return {
                "type": "ir.actions.act_window",
                "name": "Sync Report",
                "res_model": "woo.report",
                "view_mode": "form",
                "res_id": self.report_id.id,
                "target": "current",
            }
        if self.webhook_log_id:
            return {
                "type": "ir.actions.act_window",
                "name": "Webhook Log",
                "res_model": "woo.webhook.log",
                "view_mode": "form",
                "res_id": self.webhook_log_id.id,
                "target": "current",
            }
        if self.model_name and self.res_id and self.model_name in self.env:
            return {
                "type": "ir.actions.act_window",
                "name": "Record",
                "res_model": self.model_name,
                "view_mode": "form",
                "res_id": self.res_id,
                "target": "current",
            }
        return False


class WooSyncTimelineProductTemplate(models.Model):
    _inherit = "product.template"

    woo_timeline_ids = fields.One2many("woo.sync.timeline", "product_tmpl_id", string="Woo Sync Timeline", readonly=True)
    woo_timeline_count = fields.Integer(compute="_compute_woo_timeline_count")

    def _compute_woo_timeline_count(self):
        grouped = self.env["woo.sync.timeline"].read_group(
            [("product_tmpl_id", "in", self.ids)],
            ["product_tmpl_id"],
            ["product_tmpl_id"],
        )
        counts = {entry["product_tmpl_id"][0]: entry["product_tmpl_id_count"] for entry in grouped}
        for rec in self:
            rec.woo_timeline_count = counts.get(rec.id, 0)

    def action_open_woo_sync_history(self):
        self.ensure_one()
        action = self.env.ref("woo_connector.action_woo_sync_timeline").read()[0]
        action["domain"] = [("product_tmpl_id", "=", self.id)]
        action["context"] = {"default_product_tmpl_id": self.id}
        return action


class WooSyncTimelineSaleOrder(models.Model):
    _inherit = "sale.order"

    woo_timeline_ids = fields.One2many("woo.sync.timeline", "sale_order_id", string="Woo Sync Timeline", readonly=True)
    woo_timeline_count = fields.Integer(compute="_compute_woo_timeline_count")

    def _compute_woo_timeline_count(self):
        grouped = self.env["woo.sync.timeline"].read_group(
            [("sale_order_id", "in", self.ids)],
            ["sale_order_id"],
            ["sale_order_id"],
        )
        counts = {entry["sale_order_id"][0]: entry["sale_order_id_count"] for entry in grouped}
        for rec in self:
            rec.woo_timeline_count = counts.get(rec.id, 0)

    def action_open_woo_sync_history(self):
        self.ensure_one()
        action = self.env.ref("woo_connector.action_woo_sync_timeline").read()[0]
        action["domain"] = [("sale_order_id", "=", self.id)]
        action["context"] = {"default_sale_order_id": self.id}
        return action


class WooSyncTimelinePartner(models.Model):
    _inherit = "res.partner"

    woo_timeline_ids = fields.One2many("woo.sync.timeline", "partner_id", string="Woo Sync Timeline", readonly=True)
    woo_timeline_count = fields.Integer(compute="_compute_woo_timeline_count")

    def _compute_woo_timeline_count(self):
        grouped = self.env["woo.sync.timeline"].read_group(
            [("partner_id", "in", self.ids)],
            ["partner_id"],
            ["partner_id"],
        )
        counts = {entry["partner_id"][0]: entry["partner_id_count"] for entry in grouped}
        for rec in self:
            rec.woo_timeline_count = counts.get(rec.id, 0)

    def action_open_woo_sync_history(self):
        self.ensure_one()
        action = self.env.ref("woo_connector.action_woo_sync_timeline").read()[0]
        action["domain"] = [("partner_id", "=", self.id)]
        action["context"] = {"default_partner_id": self.id}
        return action


class WooSyncTimelineCategory(models.Model):
    _inherit = "product.category"

    woo_timeline_ids = fields.One2many("woo.sync.timeline", "category_id", string="Woo Sync Timeline", readonly=True)
    woo_timeline_count = fields.Integer(compute="_compute_woo_timeline_count")

    def _compute_woo_timeline_count(self):
        grouped = self.env["woo.sync.timeline"].read_group(
            [("category_id", "in", self.ids)],
            ["category_id"],
            ["category_id"],
        )
        counts = {entry["category_id"][0]: entry["category_id_count"] for entry in grouped}
        for rec in self:
            rec.woo_timeline_count = counts.get(rec.id, 0)

    def action_open_woo_sync_history(self):
        self.ensure_one()
        action = self.env.ref("woo_connector.action_woo_sync_timeline").read()[0]
        action["domain"] = [("category_id", "=", self.id)]
        action["context"] = {"default_category_id": self.id}
        return action


class WooSyncTimelineCoupon(models.Model):
    _inherit = "woo.coupon.sync"

    woo_timeline_ids = fields.One2many("woo.sync.timeline", "coupon_sync_id", string="Woo Sync Timeline", readonly=True)
    woo_timeline_count = fields.Integer(compute="_compute_woo_timeline_count")

    def _compute_woo_timeline_count(self):
        grouped = self.env["woo.sync.timeline"].read_group(
            [("coupon_sync_id", "in", self.ids)],
            ["coupon_sync_id"],
            ["coupon_sync_id"],
        )
        counts = {entry["coupon_sync_id"][0]: entry["coupon_sync_id_count"] for entry in grouped}
        for rec in self:
            rec.woo_timeline_count = counts.get(rec.id, 0)

    def action_open_woo_sync_history(self):
        self.ensure_one()
        action = self.env.ref("woo_connector.action_woo_sync_timeline").read()[0]
        action["domain"] = [("coupon_sync_id", "=", self.id)]
        action["context"] = {"default_coupon_sync_id": self.id}
        return action
