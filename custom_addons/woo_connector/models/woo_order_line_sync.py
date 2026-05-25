from odoo import models, fields


class WooOrderLineSync(models.Model):
    _name = "woo.order.line.sync"
    _description = "WooCommerce Order Line"
    _order = "id asc"

    order_sync_id = fields.Many2one(
        "woo.order.sync",
        string="Woo Order",
        required=True,
        ondelete="cascade",
    )

    woo_line_id = fields.Char(
        string="Woo Line ID",
        required=True,
        index=True,
    )

    product_name = fields.Char(required=True)
    sku = fields.Char()
    quantity = fields.Float()
    price_unit = fields.Float()
    subtotal = fields.Float()

    product_id = fields.Many2one(
        "product.product",
        string="Odoo Product",
        ondelete="set null",
    )
