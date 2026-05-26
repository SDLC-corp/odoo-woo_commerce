from odoo import _, api, fields, models
from odoo.exceptions import UserError


def _manual_toast(title, message, level="success", sticky=False):
    return {
        "type": "ir.actions.client",
        "tag": "display_notification",
        "params": {
            "title": title,
            "message": message,
            "type": level,
            "sticky": sticky,
        },
    }


class WooManualRecordSyncWizard(models.TransientModel):
    _name = "woo.manual.record.sync.wizard"
    _description = "Woo Manual Record Sync Wizard"

    instance_id = fields.Many2one(
        "woo.instance",
        string="Woo Instance",
        required=True,
        domain=[("active", "=", True)],
    )
    target_model = fields.Char(required=True)
    target_id = fields.Integer(required=True)
    callback_method = fields.Char(required=True)

    def action_confirm(self):
        self.ensure_one()
        record = self.env[self.target_model].browse(self.target_id).exists()
        if not record:
            raise UserError(_("The target record no longer exists."))
        if not hasattr(record, self.callback_method):
            raise UserError(_("Callback method '%s' is missing.") % self.callback_method)
        return getattr(record, self.callback_method)(instance=self.instance_id, via_wizard=True)


def _manual_instance_field_name(record):
    record.ensure_one()
    for field_name in ("woo_instance_id", "instance_id"):
        if field_name in record._fields:
            return field_name
    return False


def _open_manual_instance_wizard(record, callback_method):
    record.ensure_one()
    wizard = record.env["woo.manual.record.sync.wizard"].create(
        {
            "target_model": record._name,
            "target_id": record.id,
            "callback_method": callback_method,
        }
    )
    return {
        "type": "ir.actions.act_window",
        "name": _("Select Woo Instance"),
        "res_model": "woo.manual.record.sync.wizard",
        "view_mode": "form",
        "res_id": wizard.id,
        "target": "new",
    }


def _resolve_manual_instance(record, callback_method, instance=False):
    record.ensure_one()
    if instance:
        return instance, False
    forced_instance_id = record.env.context.get("force_instance_id")
    if forced_instance_id:
        forced = record.env["woo.instance"].browse(forced_instance_id).exists()
        if forced:
            return forced, False

    field_name = _manual_instance_field_name(record)
    linked_instance = record[field_name] if field_name else False
    if linked_instance:
        return linked_instance, False

    instances = record.env["woo.instance"].search([("active", "=", True)])
    if len(instances) == 1:
        resolved = instances[0]
        if field_name:
            record.write({field_name: resolved.id})
        return resolved, False
    if len(instances) > 1:
        return False, _open_manual_instance_wizard(record, callback_method)
    raise UserError(_("No active WooCommerce instance found."))


def _manual_sync_report(record, instance, operation_type, sync_direction, status, message, woo_id=None, payload=None, error_message=None):
    record.ensure_one()
    payload_data = {
        "source": "manual_record_sync",
        "target_model": record._name,
        "target_id": record.id,
        "operation_type": operation_type,
        "sync_direction": sync_direction,
        "woo_id": woo_id or False,
        "payload": payload or {},
    }
    return instance._create_sync_report(
        operation="Manual Record Sync (%s)" % operation_type.title(),
        status=status,
        message=message,
        mode="manual",
        source_action="manual_record_sync",
        reference=str(woo_id) if woo_id else False,
        operation_type=operation_type,
        sync_direction=sync_direction,
        woo_id=str(woo_id) if woo_id else False,
        payload_data=payload_data,
        error_message=error_message,
    )


def _create_manual_preview(record, instance, record_type, woo_id):
    record.ensure_one()
    preview = record.env["woo.sync.preview"].create_and_run_preview(
        {
            "name": _("Preview - Manual Record Import"),
            "source_mode": "manual_record",
            "instance_id": instance.id,
            "record_type": record_type,
            "woo_id": str(woo_id),
            "target_model": record._name,
            "target_id": record.id,
            "update_existing": True,
        }
    )
    return preview.action_open_preview()


class ProductTemplate(models.Model):
    _inherit = "product.template"

    def action_woo_create(self, instance=False, via_wizard=False):
        return self.action_manual_export_to_woo(instance=instance, via_wizard=via_wizard)

    def action_woo_update(self, instance=False, via_wizard=False):
        return self.action_manual_export_to_woo(instance=instance, via_wizard=via_wizard)

    def action_manual_import_from_woo(self, instance=False, via_wizard=False):
        self.ensure_one()
        resolved_instance, wizard_action = _resolve_manual_instance(self, "action_manual_import_from_woo", instance=instance)
        if wizard_action:
            return wizard_action

        woo_id = (self.woo_product_id or "").strip()
        if not woo_id:
            raise UserError(_("Woo Product ID is required to import/refresh this product."))

        payload = False
        try:
            wcapi = resolved_instance._get_wcapi(resolved_instance)
            response = wcapi.get(f"products/{woo_id}")
            if response.status_code != 200:
                raise UserError(response.text)
            payload = response.json()
            if not isinstance(payload, dict):
                raise UserError(_("Unexpected WooCommerce product response format."))

            sync_result = self.env["woo.webhook.sync"].sudo().process_single_import(
                record_type="product",
                payload=payload,
                instance=resolved_instance,
                source_action="manual_record_sync",
                log_result=False,
            )

            vals = {
                "woo_instance_id": resolved_instance.id,
                "woo_product_id": str(payload.get("id") or woo_id),
                "woo_last_sync": fields.Datetime.now(),
            }
            if payload.get("name"):
                vals["name"] = payload.get("name")
            if payload.get("sku") or payload.get("slug"):
                vals["default_code"] = payload.get("sku") or payload.get("slug")
            sale_price_raw = payload.get("sale_price")
            regular_price_raw = payload.get("regular_price")
            vals["list_price"] = (
                float(sale_price_raw)
                if sale_price_raw not in (None, "")
                else float(regular_price_raw or 0.0)
            )
            if "sale_price" in self._fields:
                vals["sale_price"] = float(sale_price_raw or 0.0)
            self.write(vals)

            message = (
                (sync_result or {}).get("message")
                or (_("Product '%s' refreshed from WooCommerce.") % self.display_name)
            )
            _manual_sync_report(self, 
                resolved_instance,
                operation_type="product",
                sync_direction="import",
                status="success",
                message=message,
                woo_id=vals["woo_product_id"],
                payload=payload,
            )
            return _manual_toast(_("WooCommerce"), message, level="success")
        except Exception as exc:
            error_message = str(exc)
            _manual_sync_report(self, 
                resolved_instance,
                operation_type="product",
                sync_direction="import",
                status="failed",
                message=error_message,
                woo_id=woo_id or False,
                payload=payload,
                error_message=error_message,
            )
            raise UserError(error_message)

    def action_manual_preview_from_woo(self, instance=False, via_wizard=False):
        self.ensure_one()
        resolved_instance, wizard_action = _resolve_manual_instance(self, "action_manual_preview_from_woo", instance=instance)
        if wizard_action:
            return wizard_action
        woo_id = (self.woo_product_id or "").strip()
        if not woo_id:
            raise UserError(_("Woo Product ID is required to preview this import."))
        return _create_manual_preview(self, resolved_instance, "product", woo_id)

    def action_manual_export_to_woo(self, instance=False, via_wizard=False):
        self.ensure_one()
        resolved_instance, wizard_action = _resolve_manual_instance(self, "action_manual_export_to_woo", instance=instance)
        if wizard_action:
            return wizard_action

        if not self.default_code and not self.woo_product_id:
            raise UserError(_("Set Internal Reference (SKU) before exporting a new product to avoid duplicates."))

        request_payload = {
            "name": self.name,
            "sku": self.default_code or "",
            "regular_price": str(self.list_price or 0.0),
            "sale_price": str(getattr(self, "sale_price", 0.0) or 0.0) if getattr(self, "sale_price", False) else "",
        }
        request_payload = {k: v for k, v in request_payload.items() if v not in (None, "")}

        response_payload = False
        woo_id = (self.woo_product_id or "").strip()
        matched_existing_by_sku = False
        sku_match_message = False
        try:
            wcapi = resolved_instance._get_wcapi(resolved_instance)
            if woo_id:
                response = wcapi.put(f"products/{woo_id}", request_payload)
            else:
                existing_id = False
                if self.default_code:
                    woo_match = resolved_instance._find_woo_product_by_sku(self.default_code)
                    found_product = woo_match.get("product")
                    if found_product:
                        existing_id = str(found_product.get("id"))
                        matched_existing_by_sku = True
                if existing_id:
                    woo_id = existing_id
                    response = wcapi.put(f"products/{woo_id}", request_payload)
                else:
                    response = wcapi.post("products", request_payload)

            if response.status_code not in (200, 201):
                raise UserError(response.text)

            response_payload = response.json()
            if not isinstance(response_payload, dict):
                raise UserError(_("Unexpected WooCommerce product response format."))

            self.env["woo.webhook.sync"].sudo().process_single_import(
                record_type="product",
                payload=response_payload,
                instance=resolved_instance,
                source_action="manual_record_sync",
                log_result=False,
            )

            linked_woo_id = str(response_payload.get("id") or woo_id)
            resolved_instance._link_product_with_woo_id(self, linked_woo_id, instance=resolved_instance)
            self.write({"woo_last_sync": fields.Datetime.now()})

            if matched_existing_by_sku and self.default_code:
                sku_match_message = _(
                    "Product matched by SKU %(sku)s and Woo ID %(woo)s was linked."
                ) % {
                    "sku": self.default_code,
                    "woo": linked_woo_id,
                }

            message = sku_match_message or (_("Product '%s' exported to WooCommerce.") % self.display_name)
            _manual_sync_report(self, 
                resolved_instance,
                operation_type="product",
                sync_direction="export",
                status="success",
                message=message,
                woo_id=linked_woo_id,
                payload={"request": request_payload, "response": response_payload},
            )
            return _manual_toast(_("WooCommerce"), message, level="success")
        except Exception as exc:
            error_message = str(exc)
            _manual_sync_report(self, 
                resolved_instance,
                operation_type="product",
                sync_direction="export",
                status="failed",
                message=error_message,
                woo_id=woo_id or False,
                payload={"request": request_payload, "response": response_payload},
                error_message=error_message,
            )
            raise UserError(error_message)


class SaleOrder(models.Model):
    _inherit = "sale.order"

    woo_instance_id = fields.Many2one("woo.instance", string="Woo Instance", ondelete="set null", copy=False)
    woo_order_id = fields.Char(string="Woo Order ID", copy=False, index=True)

    def action_manual_import_from_woo(self, instance=False, via_wizard=False):
        self.ensure_one()
        resolved_instance, wizard_action = _resolve_manual_instance(self, "action_manual_import_from_woo", instance=instance)
        if wizard_action:
            return wizard_action

        woo_id = (self.woo_order_id or "").strip()
        if not woo_id:
            raise UserError(_("Woo Order ID is required to import/refresh this order."))

        payload = False
        try:
            payload = resolved_instance.fetch_order(woo_id)
            if not isinstance(payload, dict):
                raise UserError(_("Unexpected WooCommerce order response format."))

            self.env["woo.webhook.sync"].sudo().process_single_import(
                record_type="order",
                payload=payload,
                instance=resolved_instance,
                source_action="manual_record_sync",
                log_result=False,
            )

            sync_order = self.env["woo.order.sync"].search(
                [
                    ("instance_id", "=", resolved_instance.id),
                    ("woo_order_id", "=", str(woo_id)),
                ],
                limit=1,
            )
            if sync_order and sync_order.sale_order_id and sync_order.sale_order_id != self:
                raise UserError(
                    _("This Woo Order is already linked to another Sales Order (%s).")
                    % sync_order.sale_order_id.display_name
                )
            if sync_order and not sync_order.sale_order_id:
                sync_order.sale_order_id = self.id

            self.write({"woo_instance_id": resolved_instance.id, "woo_order_id": str(woo_id)})

            message = _("Sale Order '%s' refreshed from WooCommerce.") % self.display_name
            _manual_sync_report(self, 
                resolved_instance,
                operation_type="order",
                sync_direction="import",
                status="success",
                message=message,
                woo_id=woo_id,
                payload=payload,
            )
            return _manual_toast(_("WooCommerce"), message, level="success")
        except Exception as exc:
            error_message = str(exc)
            _manual_sync_report(self, 
                resolved_instance,
                operation_type="order",
                sync_direction="import",
                status="failed",
                message=error_message,
                woo_id=woo_id or False,
                payload=payload,
                error_message=error_message,
            )
            raise UserError(error_message)

    def action_manual_preview_from_woo(self, instance=False, via_wizard=False):
        self.ensure_one()
        resolved_instance, wizard_action = _resolve_manual_instance(self, "action_manual_preview_from_woo", instance=instance)
        if wizard_action:
            return wizard_action
        woo_id = (self.woo_order_id or "").strip()
        if not woo_id:
            raise UserError(_("Woo Order ID is required to preview this import."))
        return _create_manual_preview(self, resolved_instance, "order", woo_id)

    def action_manual_export_to_woo(self, instance=False, via_wizard=False):
        self.ensure_one()
        resolved_instance, wizard_action = _resolve_manual_instance(self, "action_manual_export_to_woo", instance=instance)
        if wizard_action:
            return wizard_action

        woo_id = (self.woo_order_id or "").strip()
        if not woo_id:
            raise UserError(
                _(
                    "Order export create is not supported in current flow. "
                    "Set Woo Order ID and use update/export."
                )
            )

        partner_email = (self.partner_id.email or "").strip().lower() if self.partner_id else False
        request_payload = {
            "status": "processing" if self.state in ("sale", "done") else "pending",
            "billing": {
                "email": partner_email,
                "first_name": (self.partner_id.name or "").split(" ")[0] if self.partner_id.name else "",
                "last_name": " ".join((self.partner_id.name or "").split(" ")[1:]) if self.partner_id.name else "",
            },
            "customer_note": self.note or "",
        }

        try:
            sync_order = self.env["woo.order.sync"].search(
                [
                    ("instance_id", "=", resolved_instance.id),
                    ("woo_order_id", "=", woo_id),
                ],
                limit=1,
            )
            if not sync_order:
                sync_order = self.env["woo.order.sync"].create(
                    {
                        "instance_id": resolved_instance.id,
                        "woo_order_id": woo_id,
                        "name": self.name,
                        "customer_name": self.partner_id.name,
                        "customer_email": partner_email,
                        "total_amount": self.amount_total,
                        "currency": self.currency_id.name,
                        "status": "pending",
                        "state": "synced",
                        "synced_on": fields.Datetime.now(),
                        "sale_order_id": self.id,
                    }
                )
            else:
                sync_order.write(
                    {
                        "sale_order_id": self.id,
                        "customer_name": self.partner_id.name,
                        "customer_email": partner_email,
                        "total_amount": self.amount_total,
                        "currency": self.currency_id.name,
                    }
                )

            sync_order.action_push_to_woo()
            self.write({"woo_instance_id": resolved_instance.id, "woo_order_id": woo_id})

            message = _("Sale Order '%s' exported to WooCommerce.") % self.display_name
            _manual_sync_report(self, 
                resolved_instance,
                operation_type="order",
                sync_direction="export",
                status="success",
                message=message,
                woo_id=woo_id,
                payload=request_payload,
            )
            return _manual_toast(_("WooCommerce"), message, level="success")
        except Exception as exc:
            error_message = str(exc)
            _manual_sync_report(self, 
                resolved_instance,
                operation_type="order",
                sync_direction="export",
                status="failed",
                message=error_message,
                woo_id=woo_id or False,
                payload=request_payload,
                error_message=error_message,
            )
            raise UserError(error_message)


class ResPartner(models.Model):
    _inherit = "res.partner"

    woo_instance_id = fields.Many2one("woo.instance", string="Woo Instance", ondelete="set null", copy=False)
    woo_customer_id = fields.Char(string="Woo Customer ID", copy=False, index=True)

    def action_manual_import_from_woo(self, instance=False, via_wizard=False):
        self.ensure_one()
        resolved_instance, wizard_action = _resolve_manual_instance(self, "action_manual_import_from_woo", instance=instance)
        if wizard_action:
            return wizard_action

        woo_id = (self.woo_customer_id or "").strip()
        if not woo_id:
            raise UserError(_("Woo Customer ID is required to import/refresh this customer."))

        payload = False
        try:
            wcapi = resolved_instance._get_wcapi(resolved_instance)
            response = wcapi.get(f"customers/{woo_id}")
            if response.status_code != 200:
                raise UserError(response.text)
            payload = response.json()
            if not isinstance(payload, dict):
                raise UserError(_("Unexpected WooCommerce customer response format."))

            self.env["woo.webhook.sync"].sudo().process_single_import(
                record_type="customer",
                payload=payload,
                instance=resolved_instance,
                source_action="manual_record_sync",
                log_result=False,
            )

            first = payload.get("first_name") or ""
            last = payload.get("last_name") or ""
            name = f"{first} {last}".strip() or payload.get("email") or self.name
            phone = (payload.get("billing") or {}).get("phone") if isinstance(payload.get("billing"), dict) else payload.get("phone")
            normalized_email = ((payload.get("email") or self.email or "").strip().lower()) or False
            self.write(
                {
                    "woo_instance_id": resolved_instance.id,
                    "woo_customer_id": str(payload.get("id") or woo_id),
                    "name": name,
                    "email": normalized_email,
                    "phone": phone or self.phone,
                }
            )

            message = _("Customer '%s' refreshed from WooCommerce.") % self.display_name
            _manual_sync_report(self, 
                resolved_instance,
                operation_type="customer",
                sync_direction="import",
                status="success",
                message=message,
                woo_id=self.woo_customer_id,
                payload=payload,
            )
            return _manual_toast(_("WooCommerce"), message, level="success")
        except Exception as exc:
            error_message = str(exc)
            _manual_sync_report(self, 
                resolved_instance,
                operation_type="customer",
                sync_direction="import",
                status="failed",
                message=error_message,
                woo_id=woo_id or False,
                payload=payload,
                error_message=error_message,
            )
            raise UserError(error_message)

    def action_manual_preview_from_woo(self, instance=False, via_wizard=False):
        self.ensure_one()
        resolved_instance, wizard_action = _resolve_manual_instance(self, "action_manual_preview_from_woo", instance=instance)
        if wizard_action:
            return wizard_action
        woo_id = (self.woo_customer_id or "").strip()
        if not woo_id:
            raise UserError(_("Woo Customer ID is required to preview this import."))
        return _create_manual_preview(self, resolved_instance, "customer", woo_id)

    def action_manual_export_to_woo(self, instance=False, via_wizard=False):
        self.ensure_one()
        resolved_instance, wizard_action = _resolve_manual_instance(self, "action_manual_export_to_woo", instance=instance)
        if wizard_action:
            return wizard_action

        email = (self.email or "").strip().lower()
        if not email:
            raise UserError(_("Customer email is required for WooCommerce sync."))

        request_payload = {
            "email": email,
            "name": self.name,
            "phone": self.phone,
        }

        try:
            sync_customer = self.env["woo.customer.sync"].search(
                [
                    ("instance_id", "=", resolved_instance.id),
                    "|",
                    ("woo_customer_id", "=", self.woo_customer_id or ""),
                    ("email", "=ilike", email),
                ],
                limit=1,
            )
            if not sync_customer:
                sync_customer = self.env["woo.customer.sync"].create(
                    {
                        "instance_id": resolved_instance.id,
                        "name": self.name or email,
                        "email": email,
                        "phone": self.phone,
                        "woo_customer_id": self.woo_customer_id or False,
                        "state": "synced",
                        "synced_on": fields.Datetime.now(),
                    }
                )
            else:
                sync_customer.write(
                    {
                        "name": self.name or sync_customer.name,
                        "email": email,
                        "phone": self.phone,
                    }
                )

            sync_customer.action_push_to_woo()
            self.write(
                {
                    "woo_instance_id": resolved_instance.id,
                    "woo_customer_id": sync_customer.woo_customer_id,
                }
            )

            message = _("Customer '%s' exported to WooCommerce.") % self.display_name
            _manual_sync_report(self, 
                resolved_instance,
                operation_type="customer",
                sync_direction="export",
                status="success",
                message=message,
                woo_id=self.woo_customer_id,
                payload=request_payload,
            )
            return _manual_toast(_("WooCommerce"), message, level="success")
        except Exception as exc:
            error_message = str(exc)
            _manual_sync_report(self, 
                resolved_instance,
                operation_type="customer",
                sync_direction="export",
                status="failed",
                message=error_message,
                woo_id=self.woo_customer_id or False,
                payload=request_payload,
                error_message=error_message,
            )
            raise UserError(error_message)


class ProductCategory(models.Model):
    _inherit = "product.category"

    woo_instance_id = fields.Many2one("woo.instance", string="Woo Instance", ondelete="set null", copy=False)
    woo_category_id = fields.Char(string="Woo Category ID", copy=False, index=True)

    def action_manual_import_from_woo(self, instance=False, via_wizard=False):
        self.ensure_one()
        resolved_instance, wizard_action = _resolve_manual_instance(self, "action_manual_import_from_woo", instance=instance)
        if wizard_action:
            return wizard_action

        woo_id = (self.woo_category_id or "").strip()
        if not woo_id:
            raise UserError(_("Woo Category ID is required to import/refresh this category."))

        payload = False
        try:
            wcapi = resolved_instance._get_wcapi(resolved_instance)
            response = wcapi.get(f"products/categories/{woo_id}")
            if response.status_code != 200:
                raise UserError(response.text)
            payload = response.json()
            if not isinstance(payload, dict):
                raise UserError(_("Unexpected WooCommerce category response format."))

            self.env["woo.webhook.sync"].sudo().process_single_import(
                record_type="category",
                payload=payload,
                instance=resolved_instance,
                source_action="manual_record_sync",
                log_result=False,
            )

            self.write(
                {
                    "woo_instance_id": resolved_instance.id,
                    "woo_category_id": str(payload.get("id") or woo_id),
                    "name": payload.get("name") or self.name,
                }
            )

            message = _("Category '%s' refreshed from WooCommerce.") % self.display_name
            _manual_sync_report(self, 
                resolved_instance,
                operation_type="category",
                sync_direction="import",
                status="success",
                message=message,
                woo_id=self.woo_category_id,
                payload=payload,
            )
            return _manual_toast(_("WooCommerce"), message, level="success")
        except Exception as exc:
            error_message = str(exc)
            _manual_sync_report(self, 
                resolved_instance,
                operation_type="category",
                sync_direction="import",
                status="failed",
                message=error_message,
                woo_id=woo_id or False,
                payload=payload,
                error_message=error_message,
            )
            raise UserError(error_message)

    def action_manual_preview_from_woo(self, instance=False, via_wizard=False):
        self.ensure_one()
        resolved_instance, wizard_action = _resolve_manual_instance(self, "action_manual_preview_from_woo", instance=instance)
        if wizard_action:
            return wizard_action
        woo_id = (self.woo_category_id or "").strip()
        if not woo_id:
            raise UserError(_("Woo Category ID is required to preview this import."))
        return _create_manual_preview(self, resolved_instance, "category", woo_id)

    def action_manual_export_to_woo(self, instance=False, via_wizard=False):
        self.ensure_one()
        resolved_instance, wizard_action = _resolve_manual_instance(self, "action_manual_export_to_woo", instance=instance)
        if wizard_action:
            return wizard_action

        request_payload = {"name": self.name}

        try:
            sync_category = self.env["woo.category.sync"].search(
                [
                    ("instance_id", "=", resolved_instance.id),
                    "|",
                    ("woo_category_id", "=", self.woo_category_id or ""),
                    ("name", "=", self.name),
                ],
                limit=1,
            )
            if not sync_category:
                sync_category = self.env["woo.category.sync"].create(
                    {
                        "instance_id": resolved_instance.id,
                        "name": self.name,
                        "woo_category_id": self.woo_category_id or False,
                        "state": "synced",
                        "synced_on": fields.Datetime.now(),
                    }
                )
            else:
                sync_category.write({"name": self.name})

            sync_category.action_push_to_woo()
            self.write(
                {
                    "woo_instance_id": resolved_instance.id,
                    "woo_category_id": sync_category.woo_category_id,
                }
            )

            message = _("Category '%s' exported to WooCommerce.") % self.display_name
            _manual_sync_report(self, 
                resolved_instance,
                operation_type="category",
                sync_direction="export",
                status="success",
                message=message,
                woo_id=self.woo_category_id,
                payload=request_payload,
            )
            return _manual_toast(_("WooCommerce"), message, level="success")
        except Exception as exc:
            error_message = str(exc)
            _manual_sync_report(self, 
                resolved_instance,
                operation_type="category",
                sync_direction="export",
                status="failed",
                message=error_message,
                woo_id=self.woo_category_id or False,
                payload=request_payload,
                error_message=error_message,
            )
            raise UserError(error_message)
