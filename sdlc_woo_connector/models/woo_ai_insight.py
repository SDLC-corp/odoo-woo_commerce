import json

from odoo import api, fields, models


class WooAIInsight(models.Model):
    _name = "woo.ai.insight"
    _description = "WooCommerce AI Insight"
    _order = "generated_at desc, id desc"

    name = fields.Char(required=True, default="AI Insight")
    instance_id = fields.Many2one("woo.instance", string="Woo Instance", ondelete="cascade")
    scope = fields.Selection(
        [("instance", "Instance"), ("all", "All Instances")],
        default="instance",
        required=True,
    )
    range_days = fields.Integer(string="Range Days", default=30, required=True)
    summary_text = fields.Text(string="Summary")
    insight_json = fields.Text(string="Structured Insight JSON")
    status = fields.Selection(
        [("draft", "Draft"), ("success", "Success"), ("fallback", "Fallback"), ("failed", "Failed")],
        default="draft",
        required=True,
    )
    generated_at = fields.Datetime(string="Generated On")
    error_message = fields.Text(string="Error")

    _sql_constraints = [
        (
            "woo_ai_insight_scope_uniq",
            "unique(instance_id, scope, range_days)",
            "Only one latest AI insight record is stored per scope and date range.",
        )
    ]

    @api.model
    def upsert_latest(self, values):
        domain = [
            ("scope", "=", values.get("scope")),
            ("range_days", "=", values.get("range_days")),
        ]
        if values.get("scope") == "instance":
            domain.append(("instance_id", "=", values.get("instance_id")))
        else:
            domain.append(("instance_id", "=", False))

        record = self.search(domain, limit=1)
        if record:
            record.write(values)
            return record
        return self.create(values)

    def get_payload(self):
        self.ensure_one()
        try:
            payload = json.loads(self.insight_json or "{}")
        except Exception:
            payload = {}
        payload.update(
            {
                "summary_text": self.summary_text or "",
                "status": self.status,
                "generated_at": self.generated_at,
                "error_message": self.error_message or "",
            }
        )
        return payload
