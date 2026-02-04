from odoo import models, fields


class WooCouponSync(models.Model):
    _name = "woo.coupon.sync"
    _description = "WooCommerce Coupon Sync"
    _order = "synced_on desc"

    instance_id = fields.Many2one(
        "woo.instance",
        string="Woo Instance",
        required=True,
        ondelete="cascade",
    )

    name = fields.Char(string="Coupon Code", required=True)
    woo_coupon_id = fields.Char(string="Woo Coupon ID", index=True)
    discount_type = fields.Selection([
        ("percent", "Percentage"),
        ("fixed_cart", "Fixed Cart"),
        ("fixed_product", "Fixed Product"),
    ])
    amount = fields.Float()
    usage_limit = fields.Integer()
    usage_count = fields.Integer()
    expiry_date = fields.Datetime()
    status = fields.Char()
    state = fields.Selection([
        ("synced", "Synced"),
        ("failed", "Failed"),
    ], default="synced")
    synced_on = fields.Datetime()
