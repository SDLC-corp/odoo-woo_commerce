from odoo import models, fields


class WooReportLine(models.Model):
    _name = "woo.report.line"
    _description = "Woo Sync Report Line"
    _order = "id desc"

    report_id = fields.Many2one(
        "woo.report",
        ondelete="set null",
    )
    active = fields.Boolean(default=True)

    record_type = fields.Char(string="Record Type")
    source_action = fields.Char(string="Source Action")
    woo_id = fields.Char(string="Woo ID")
    name = fields.Char(string="Record Name")
    status = fields.Selection(
        [
            ("success", "Success"),
            ("error", "Error"),
        ],
        required=True,
        default="success",
    )
    error_message = fields.Text(string="Error Message")
