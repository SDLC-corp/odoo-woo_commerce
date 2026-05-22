from odoo import fields, models


class WooConnectionHealthLog(models.Model):
    _name = "woo.connection.health.log"
    _description = "Woo Connection Health Log"
    _order = "checked_at desc, id desc"

    instance_id = fields.Many2one(
        "woo.instance",
        string="Woo Instance",
        required=True,
        ondelete="cascade",
        index=True,
    )
    check_type = fields.Char(required=True, index=True)
    status = fields.Selection(
        [
            ("success", "Success"),
            ("warning", "Warning"),
            ("failed", "Failed"),
        ],
        default="failed",
        required=True,
        index=True,
    )
    message = fields.Text(required=True)
    response_time_ms = fields.Float(string="Response Time (ms)")
    checked_at = fields.Datetime(default=fields.Datetime.now, required=True, index=True)
    details_json = fields.Text(string="Details JSON")
