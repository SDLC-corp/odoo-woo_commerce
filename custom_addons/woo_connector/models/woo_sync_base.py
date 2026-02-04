from odoo import models, fields

class WooSyncBase(models.AbstractModel):
    _name = "woo.sync.base"
    _description = "Woo Sync Base"
    _inherit = ["mail.thread"]

    instance_id = fields.Many2one("woo.instance", required=True)
    state = fields.Selection(
        [("draft", "Draft"), ("synced", "Synced"), ("error", "Error")],
        default="draft",
        tracking=True
    )
    synced_on = fields.Datetime()
    error_message = fields.Text()

    # MUST BE OVERRIDDEN
    def _woo_endpoint(self):
        raise NotImplementedError

    def _woo_unique_field(self):
        raise NotImplementedError

    def _prepare_vals(self, woo_data):
        raise NotImplementedError
