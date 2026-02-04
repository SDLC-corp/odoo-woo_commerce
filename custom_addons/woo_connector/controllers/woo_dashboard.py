from odoo import http
from odoo.http import request


class WooDashboardController(http.Controller):

    @http.route('/woo/dashboard/data', type='json', auth='user')
    def woo_dashboard_data(self):
        return request.env['woo.dashboard'].get_dashboard_data()
