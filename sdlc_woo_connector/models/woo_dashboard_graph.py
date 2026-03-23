from odoo import models, fields
import requests
from odoo.exceptions import UserError


class WooDashboardGraph(models.Model):
    _name = "woo.dashboard.graph"
    _description = "Woo Dashboard Graph"
    _auto = False

    date = fields.Date()
    revenue = fields.Float()
    orders = fields.Integer()

    def get_graph_data(self, date_from, date_to):
        instance = self.env["woo.instance"].search(
            [("active", "=", True)], limit=1
        )
        if not instance:
            raise UserError("No active Woo instance.")

        auth = (instance.wp_username, instance.application_password)
        base = instance.shop_url.rstrip("/")

        r = requests.get(
            f"{base}/wp-json/wc-analytics/reports/revenue/stats",
            auth=auth,
            params={
                "after": date_from,
                "before": date_to,
                "interval": "day",
            },
        )

        result = []
        for row in r.json().get("intervals", []):
            result.append({
                "date": row["interval"],
                "revenue": row["subtotals"]["total_sales"],
                "orders": row["subtotals"]["orders_count"],
            })

        return result
