from odoo import models, fields

class WooAnalyticsProduct(models.Model):
    _name = "woo.analytics.product"
    _description = "WooCommerce Product Analytics"

    product_id = fields.Char()
    product_name = fields.Char()
    items_sold = fields.Integer()
    net_revenue = fields.Float()
    instance_id = fields.Many2one("woo.instance", required=True)
