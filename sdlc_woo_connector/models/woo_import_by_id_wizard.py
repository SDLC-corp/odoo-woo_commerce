from odoo import _, fields, models
from odoo.exceptions import UserError


class WooImportByIdWizard(models.TransientModel):
    _name = "woo.import.by.id.wizard"
    _description = "Woo Import By ID"

    instance_id = fields.Many2one(
        "woo.instance",
        string="Woo Instance",
        required=True,
        default=lambda self: self._default_instance_id(),
        help="Source WooCommerce instance to pull the record from.",
    )
    record_type = fields.Selection(
        [
            ("product", "Product"),
            ("order", "Order"),
            ("customer", "Customer"),
            ("category", "Category"),
            ("coupon", "Coupon"),
        ],
        required=True,
        default="product",
        help="Type of WooCommerce record to import (product, order, customer, category, or coupon).",
    )
    woo_id = fields.Char(
        string="Woo ID",
        required=True,
        help="Numeric ID of the record in WooCommerce. Look it up in the Woo admin URL or in the relevant list view.",
    )
    update_existing = fields.Boolean(
        string="Update existing record if found",
        default=True,
        help="If on, an existing Odoo record with the same Woo ID is updated. If off, the import is skipped when a match is found.",
    )

    def _default_instance_id(self):
        active_model = self.env.context.get("active_model")
        active_id = self.env.context.get("active_id")
        if active_model == "woo.instance" and active_id:
            return active_id
        instance = self.env["woo.instance"].search([("active", "=", True)], limit=1)
        return instance.id if instance else False

    def _normalize_woo_id(self):
        self.ensure_one()
        value = (self.woo_id or "").strip()
        if not value:
            raise UserError(_("Please provide a Woo ID."))
        return value

    def _api_endpoint_for_type(self, record_type):
        endpoint_map = {
            "product": "products",
            "order": "orders",
            "customer": "customers",
            "category": "products/categories",
            "coupon": "coupons",
        }
        endpoint = endpoint_map.get(record_type)
        if not endpoint:
            raise UserError(_("Unsupported record type: %s") % record_type)
        return endpoint

    def _fetch_payload_from_woo(self, woo_id):
        self.ensure_one()
        endpoint = self._api_endpoint_for_type(self.record_type)
        wcapi = self.instance_id._get_wcapi(self.instance_id)
        response = wcapi.get(f"{endpoint}/{woo_id}")
        if response.status_code == 404:
            raise UserError(
                _("%s with Woo ID '%s' was not found in WooCommerce.")
                % (self.record_type.title(), woo_id)
            )
        if response.status_code != 200:
            raise UserError(
                _("Failed to fetch %s from WooCommerce.\nStatus: %s\nResponse: %s")
                % (self.record_type, response.status_code, response.text)
            )
        payload = response.json()
        if not isinstance(payload, dict):
            raise UserError(
                _("Unexpected WooCommerce response for %s ID '%s'.")
                % (self.record_type, woo_id)
            )
        return payload

    def _find_existing_record(self, payload, woo_id):
        self.ensure_one()
        instance = self.instance_id

        if self.record_type == "product":
            record = self.env["woo.product.sync"].search(
                [
                    ("instance_id", "=", instance.id),
                    ("woo_product_id", "=", str(woo_id)),
                ],
                limit=1,
            )
            if record:
                return record
            if instance.smart_sku_matching:
                sku = instance._normalize_sku(payload.get("sku") or payload.get("slug"))
                if sku:
                    match_info = instance._find_odoo_product_by_sku(sku, instance=instance)
                    return match_info.get("product_tmpl")
            return False

        if self.record_type == "order":
            return self.env["woo.order.sync"].search(
                [
                    ("instance_id", "=", instance.id),
                    ("woo_order_id", "=", str(woo_id)),
                ],
                limit=1,
            )

        if self.record_type == "customer":
            record = self.env["woo.customer.sync"].search(
                [
                    ("instance_id", "=", instance.id),
                    ("woo_customer_id", "=", str(woo_id)),
                ],
                limit=1,
            )
            if record:
                return record
            email = (payload.get("email") or "").strip().lower()
            if email:
                return self.env["woo.customer.sync"].search(
                    [
                        ("instance_id", "=", instance.id),
                        ("email", "=ilike", email),
                    ],
                    limit=1,
                )
            return False

        if self.record_type == "category":
            record = self.env["woo.category.sync"].search(
                [
                    ("instance_id", "=", instance.id),
                    ("woo_category_id", "=", str(woo_id)),
                ],
                limit=1,
            )
            if record:
                return record
            name = payload.get("name")
            if name:
                return self.env["woo.category.sync"].search(
                    [
                        ("instance_id", "=", instance.id),
                        ("name", "=", name),
                    ],
                    limit=1,
                )
            return False

        if self.record_type == "coupon":
            record = self.env["woo.coupon.sync"].search(
                [
                    ("instance_id", "=", instance.id),
                    ("woo_coupon_id", "=", str(woo_id)),
                ],
                limit=1,
            )
            if record:
                return record
            code = payload.get("code")
            if code:
                return self.env["woo.coupon.sync"].search(
                    [
                        ("instance_id", "=", instance.id),
                        ("name", "=", code),
                    ],
                    limit=1,
                )
            return False

        return False

    def _display_name_from_payload(self, payload, woo_id):
        self.ensure_one()
        if self.record_type == "order":
            return payload.get("number") or payload.get("id") or woo_id
        if self.record_type == "coupon":
            return payload.get("code") or payload.get("id") or woo_id
        if self.record_type == "customer":
            first = payload.get("first_name") or ""
            last = payload.get("last_name") or ""
            return f"{first} {last}".strip() or payload.get("email") or woo_id
        return payload.get("name") or payload.get("id") or woo_id

    def action_import_record(self):
        self.ensure_one()

        if not self.instance_id:
            raise UserError(_("Please select a Woo Instance."))

        woo_id = self._normalize_woo_id()
        payload = False
        operation_label = "Manual Import by Woo ID (%s)" % self.record_type.title()
        report_common = {
            "operation": operation_label,
            "mode": "manual",
            "source_action": "manual_import_by_id",
            "reference": woo_id,
            "operation_type": self.record_type,
            "sync_direction": "import",
            "woo_id": woo_id,
        }

        try:
            payload = self._fetch_payload_from_woo(woo_id)
            existing = self._find_existing_record(payload, woo_id)
            if existing and not self.update_existing:
                raise UserError(
                    _(
                        "A matching %s record already exists. "
                        "Enable 'Update existing record if found' to update it."
                    )
                    % self.record_type
                )

            sync_result = self.env["woo.webhook.sync"].sudo().process_single_import(
                record_type=self.record_type,
                payload=payload,
                instance=self.instance_id,
                source_action="manual_import_by_id",
                log_result=False,
            )

            action_word = "Updated" if existing else "Imported"
            display_name = self._display_name_from_payload(payload, woo_id)
            success_message = (
                (sync_result or {}).get("message")
                or _("%s %s '%s' successfully.") % (
                    action_word,
                    self.record_type,
                    display_name,
                )
            )

            self.instance_id._create_sync_report(
                status="success",
                message=success_message,
                payload_data=payload,
                **report_common,
            )

            return {
                "type": "ir.actions.client",
                "tag": "display_notification",
                "params": {
                    "title": _("Import by Woo ID"),
                    "message": success_message,
                    "type": "success",
                    "sticky": False,
                },
            }
        except Exception as exc:
            error_message = str(exc)
            self.instance_id._create_sync_report(
                status="failed",
                message=error_message,
                error_message=error_message,
                payload_data=payload,
                **report_common,
            )
            raise UserError(error_message)

    def action_preview_sync(self):
        self.ensure_one()
        if not self.instance_id:
            raise UserError(_("Please select a Woo Instance."))
        woo_id = self._normalize_woo_id()
        preview = self.env["woo.sync.preview"].create_and_run_preview(
            {
                "name": _("Import by Woo ID #%(woo_id)s - %(type)s") % {
                    "woo_id": woo_id,
                    "type": dict(self.env["woo.sync.preview"].RECORD_TYPE_SELECTION).get(
                        self.record_type, self.record_type
                    ),
                },
                "source_mode": "import_by_id",
                "instance_id": self.instance_id.id,
                "record_type": self.record_type,
                "woo_id": woo_id,
                "update_existing": self.update_existing,
            }
        )
        return preview.action_open_preview()
