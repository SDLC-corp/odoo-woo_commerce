from odoo import models, fields

class WooAnalyticsCategory(models.Model):
    _name = "woo.analytics.category"
    _description = "WooCommerce Category Analytics"

    category_id = fields.Char()
    category_name = fields.Char()
    items_sold = fields.Integer()
    net_revenue = fields.Float()
    instance_id = fields.Many2one("woo.instance", required=True)
