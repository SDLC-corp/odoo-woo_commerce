from odoo import models, fields, _
from odoo.exceptions import UserError


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

    def _format_woo_datetime(self, value):
        if not value:
            return False
        return value.strftime("%Y-%m-%dT%H:%M:%S")

    def action_push_to_woo(self):
        self.ensure_one()

        if not self.instance_id:
            raise UserError(_("Woo instance missing."))

        wcapi = self.instance_id._get_wcapi(self.instance_id)

        payload = {
            "code": self.name,
            "discount_type": self.discount_type,
            "amount": str(self.amount or 0.0),
            "usage_limit": self.usage_limit or None,
            "date_expires": self._format_woo_datetime(self.expiry_date),
        }
        payload = {k: v for k, v in payload.items() if v not in (None, False, "")}

        if self.woo_coupon_id:
            response = wcapi.put(
                f"coupons/{self.woo_coupon_id}",
                payload
            )
        else:
            response = wcapi.post(
                "coupons",
                payload
            )

        if response.status_code not in (200, 201):
            raise UserError(response.text)

        data = response.json()
        self.write({
            "woo_coupon_id": str(data.get("id")),
            "state": "synced",
            "synced_on": fields.Datetime.now(),
        })

        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("WooCommerce"),
                "message": _("Coupon synced successfully."),
                "type": "success",
            },
        }

    def action_pull_from_woo(self):
        self.ensure_one()

        if not self.instance_id:
            raise UserError(_("Woo instance missing."))

        self.instance_id.action_sync_coupons()

        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("WooCommerce"),
                "message": _("Coupons refreshed from WooCommerce."),
                "type": "success",
            },
        }
