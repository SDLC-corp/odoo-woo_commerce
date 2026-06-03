from odoo.exceptions import UserError

class WooService:
    def __init__(self, instance):
        self.instance = instance
        self.wcapi = instance._get_wcapi(instance)

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
