from odoo.exceptions import UserError
from odoo import _

try:
    from woocommerce import API as WooAPI
except Exception:
    WooAPI = False

class WooService:
    def __init__(self, instance):
        self.instance = instance
        if not WooAPI:
            raise UserError(
                _("Missing Python dependency 'woocommerce'. Install it in the Odoo environment and restart the server.")
            )
        self.wcapi = WooAPI(
            url=instance.shop_url.rstrip("/"),
            consumer_key=instance.consumer_key,
            consumer_secret=instance.consumer_secret,
            version="wc/v3",
            timeout=30,
        )

    def get(self, endpoint, params=None):
        response = self.wcapi.get(endpoint, params=params or {})
        if response.status_code != 200:
            raise UserError(response.text)
        return response.json(), response.headers

    def post(self, endpoint, data):
        response = self.wcapi.post(endpoint, data)
        if response.status_code not in (200, 201):
            raise UserError(response.text)
        return response.json()

    def put(self, endpoint, data):
        response = self.wcapi.put(endpoint, data)
        if response.status_code != 200:
            raise UserError(response.text)
        return response.json()
