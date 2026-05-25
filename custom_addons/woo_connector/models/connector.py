
from odoo import models, fields, api
import requests
from requests.auth import HTTPBasicAuth

class WooConnector(models.Model):
    _name = 'woo.connector'
    _description = 'WooCommerce Connector'

    name = fields.Char(default="WooCommerce Connector")
    woo_url = fields.Char(string="Woo URL", required=True)
    consumer_key = fields.Char(string="Consumer Key", required=True)
    consumer_secret = fields.Char(string="Consumer Secret", required=True)

    def action_sync_products(self):
        products = self.env['product.product'].search([])
        for product in products:
            data = {
                "name": product.name,
                "sku": product.default_code or "",
                "regular_price": str(product.list_price),
                "manage_stock": True,
                "stock_quantity": int(product.qty_available),
            }
            url = f"{self.woo_url}/wp-json/wc/v3/products"
            response = requests.post(
                url,
                json=data,
                auth=HTTPBasicAuth(self.consumer_key, self.consumer_secret),
                timeout=30
            )
            if response.status_code not in (200, 201):
                raise Exception(response.text)
        return True
