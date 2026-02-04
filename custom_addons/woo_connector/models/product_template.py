from odoo import models, fields
from odoo.exceptions import UserError
from odoo import api


class ProductTemplate(models.Model):
    _inherit = "product.template"

    woo_instance_id = fields.Many2one(
        "woo.instance",
        string="Woo Instance",
        domain="[('active','=',True)]"
    )
    woo_product_id = fields.Char(string="Woo Product ID", copy=False)
    woo_status = fields.Selection(
        [
            ("draft", "Draft"),
            ("publish", "Published"),
        ],
        default="draft",
    )
    woo_last_sync = fields.Datetime(string="Last Woo Sync")

    # --------------------------------------------------
    # BUTTON ACTIONS (THIS FIXES YOUR ERROR)
    # --------------------------------------------------

    def action_woo_create(self):
        self.ensure_one()

        if not self.woo_instance_id:
            raise UserError("Please select a Woo Instance first.")

        if self.woo_product_id:
            raise UserError("This product is already linked to WooCommerce.")

        # TEMP logic (replace with real sync later)
        self.write({
            "woo_product_id": "TEMP-WOO-ID",
            "woo_status": "publish",
            "woo_last_sync": fields.Datetime.now(),
        })

        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": "WooCommerce",
                "message": "Product created in WooCommerce (demo).",
                "type": "success",
                "sticky": False,
            },
        }

    def action_woo_update(self):
        self.ensure_one()

        if not self.woo_product_id:
            raise UserError("This product is not yet linked to WooCommerce.")

        self.write({
            "woo_last_sync": fields.Datetime.now(),
        })

        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": "WooCommerce",
                "message": "Product updated in WooCommerce (demo).",
                "type": "success",
                "sticky": False,
            },
        }

    @api.model
    def create(self, vals):
        if not vals.get("woo_instance_id"):
            instance = self.env["woo.instance"].search(
                [("active", "=", True)],
                limit=1
            )
            if instance:
                vals["woo_instance_id"] = instance.id
        return super().create(vals)
