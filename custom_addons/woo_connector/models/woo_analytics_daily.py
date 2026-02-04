from odoo import models, fields

class WooAnalyticsDaily(models.Model):
    _name = "woo.analytics.daily"
    _description = "WooCommerce Daily Analytics"
    _order = "date asc"

    date = fields.Date(required=True, index=True)
    gross_sales = fields.Float()
    net_sales = fields.Float()
    orders_count = fields.Integer()
    items_sold = fields.Integer()
    instance_id = fields.Many2one("woo.instance", required=True)
