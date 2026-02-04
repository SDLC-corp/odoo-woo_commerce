from odoo import models, fields, api


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
        ],
        required=True,
        default="running",
    )
    message = fields.Text()
    run_on = fields.Datetime(
        string="Run On",
        default=fields.Datetime.now,
        readonly=True,
    )
    auto = fields.Boolean(default=False)

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

