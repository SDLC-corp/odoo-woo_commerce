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

    def _manual_sync_report(self, status, message, sync_direction, payload=None, error_message=None):
        self.ensure_one()
        return self.instance_id._create_sync_report(
            operation="Manual Record Sync (Coupon)",
            status=status,
            message=message,
            mode="manual",
            source_action="manual_record_sync",
            reference=self.woo_coupon_id or False,
            operation_type="coupon",
            sync_direction=sync_direction,
            woo_id=self.woo_coupon_id or False,
            payload_data={
                "source": "manual_record_sync",
                "target_model": self._name,
                "target_id": self.id,
                "operation_type": "coupon",
                "sync_direction": sync_direction,
                "woo_id": self.woo_coupon_id or False,
                "payload": payload or {},
            },
            error_message=error_message,
        )

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

        response_data = False
        try:
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

            response_data = response.json()
            self.write({
                "woo_coupon_id": str(response_data.get("id")),
                "state": "synced",
                "synced_on": fields.Datetime.now(),
            })

            message = _("Coupon synced successfully.")
            self._manual_sync_report(
                status="success",
                message=message,
                sync_direction="export",
                payload={"request": payload, "response": response_data},
            )
            return {
                "type": "ir.actions.client",
                "tag": "display_notification",
                "params": {
                    "title": _("WooCommerce"),
                    "message": message,
                    "type": "success",
                },
            }
        except Exception as exc:
            error_message = str(exc)
            self._manual_sync_report(
                status="failed",
                message=error_message,
                sync_direction="export",
                payload={"request": payload, "response": response_data},
                error_message=error_message,
            )
            raise UserError(error_message)

    def action_pull_from_woo(self):
        self.ensure_one()

        if not self.instance_id:
            raise UserError(_("Woo instance missing."))
        if not self.woo_coupon_id:
            raise UserError(_("Woo Coupon ID is required to import/refresh this coupon."))

        payload = False
        try:
            wcapi = self.instance_id._get_wcapi(self.instance_id)
            response = wcapi.get(f"coupons/{self.woo_coupon_id}")
            if response.status_code != 200:
                raise UserError(response.text)
            payload = response.json()
            if not isinstance(payload, dict):
                raise UserError(_("Unexpected WooCommerce coupon response format."))

            self.env["woo.webhook.sync"].sudo().process_single_import(
                record_type="coupon",
                payload=payload,
                instance=self.instance_id,
                source_action="manual_record_sync",
                log_result=False,
            )

            self.write(
                {
                    "woo_coupon_id": str(payload.get("id") or self.woo_coupon_id),
                    "name": payload.get("code") or self.name,
                    "state": "synced",
                    "synced_on": fields.Datetime.now(),
                }
            )

            message = _("Coupon refreshed from WooCommerce.")
            self._manual_sync_report(
                status="success",
                message=message,
                sync_direction="import",
                payload=payload,
            )
            return {
                "type": "ir.actions.client",
                "tag": "display_notification",
                "params": {
                    "title": _("WooCommerce"),
                    "message": message,
                    "type": "success",
                },
            }
        except Exception as exc:
            error_message = str(exc)
            self._manual_sync_report(
                status="failed",
                message=error_message,
                sync_direction="import",
                payload=payload,
                error_message=error_message,
            )
            raise UserError(error_message)

    def action_manual_preview_from_woo(self, instance=False, via_wizard=False):
        self.ensure_one()
        resolved_instance = instance or self.instance_id
        if not resolved_instance:
            raise UserError(_("Woo instance missing."))
        woo_id = (self.woo_coupon_id or "").strip()
        if not woo_id:
            raise UserError(_("Woo Coupon ID is required to preview this import."))
        preview = self.env["woo.sync.preview"].create_and_run_preview(
            {
                "name": _("Preview - Manual Record Import"),
                "source_mode": "manual_record",
                "instance_id": resolved_instance.id,
                "record_type": "coupon",
                "woo_id": woo_id,
                "target_model": self._name,
                "target_id": self.id,
                "update_existing": True,
            }
        )
        return preview.action_open_preview()
