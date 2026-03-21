from odoo import models, fields

class WooSyncStatus(models.Model):
    _name = "woo.sync.status"
    _description = "Woo Sync Status"

    instance_id = fields.Many2one(
        "woo.instance",
        required=True,
        ondelete="cascade"
    )

    last_sync = fields.Datetime()
    syncing = fields.Boolean(default=False)
    last_error = fields.Text()
