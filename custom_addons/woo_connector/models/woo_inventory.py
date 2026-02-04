from odoo import models, fields, api


class WooInventory(models.Model):
    _name = "woo.inventory"
    _description = "Woo Inventory"
    _rec_name = "product_name"

    instance_id = fields.Many2one(
        "woo.instance",
        string="Woo Instance",
        required=True,
        ondelete="cascade",
    )

    woo_product_id = fields.Char(
        string="Woo Product ID",
        required=True,
        index=True,
    )

    product_name = fields.Char(
        string="Product Name",
        required=True,
    )

    sku = fields.Char(string="SKU")

    quantity = fields.Integer(
        string="Stock Quantity",
        default=0,
    )

    stock_status = fields.Selection(
        [
            ("in_stock", "In stock"),
            ("out_of_stock", "Out of stock"),
        ],
        string="Stock Status",
        compute="_compute_stock_status",
        store=True,
    )

    @api.depends("quantity")
    def _compute_stock_status(self):
        for rec in self:
            rec.stock_status = (
                "in_stock" if rec.quantity > 0 else "out_of_stock"
            )
