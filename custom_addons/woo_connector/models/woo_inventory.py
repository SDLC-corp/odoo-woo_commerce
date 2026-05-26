from odoo import models, fields, api, _
from odoo.exceptions import UserError


class WooInventory(models.Model):
    _name = "woo.inventory"
    _description = "Woo Inventory"
    _rec_name = "product_name"

    instance_id = fields.Many2one(
        "woo.instance",
        string="Woo Instance",
        required=True,
        ondelete="cascade",
        help="WooCommerce Instance this inventory record belongs to.",
    )

    woo_product_id = fields.Char(
        string="Woo Product ID",
        required=True,
        index=True,
        help="Numeric product ID in WooCommerce that this inventory row tracks.",
    )

    product_name = fields.Char(
        string="Product Name",
        required=True,
        help="Display name of the product in WooCommerce at the time of last sync.",
    )

    sku = fields.Char(
        string="SKU",
        help="Stock Keeping Unit identifier shared between Odoo and WooCommerce.",
    )

    quantity = fields.Integer(
        string="Stock Quantity",
        default=0,
        help="On-hand stock quantity reported by WooCommerce on the last refresh.",
    )

    stock_status = fields.Selection(
        [
            ("in_stock", "In stock"),
            ("out_of_stock", "Out of stock"),
        ],
        string="Stock Status",
        compute="_compute_stock_status",
        store=True,
        help="Computed status: In stock when quantity > 0, otherwise Out of stock.",
    )

    @api.depends("quantity")
    def _compute_stock_status(self):
        for rec in self:
            rec.stock_status = (
                "in_stock" if rec.quantity > 0 else "out_of_stock"
            )

    def action_refresh_inventory(self):
        instances = self.mapped("instance_id")
        if not instances:
            instances = self.env["woo.instance"].search([
                ("active", "=", True),
            ])

        if not instances:
            raise UserError(_("No active WooCommerce instance found."))

        total = 0
        for instance in instances:
            total += instance.with_context(
                suppress_toast=True
            ).sync_inventory_from_woo() or 0

        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("WooCommerce"),
                "message": _(
                    "Inventory refreshed for %s instances."
                ) % len(instances),
                "type": "success",
            },
        }
