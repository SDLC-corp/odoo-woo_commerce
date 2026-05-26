import json
from datetime import datetime, time

from odoo import _, api, fields, models
from odoo.exceptions import UserError


class WooSyncPreview(models.Model):
    _name = "woo.sync.preview"
    _description = "Woo Sync Dry Run Preview"
    _order = "create_date desc, id desc"

    SOURCE_SELECTION = [
        ("import_by_id", "Import by Woo ID"),
        ("date_range", "Date Range Import"),
        ("manual_record", "Manual Record Import"),
    ]
    RECORD_TYPE_SELECTION = [
        ("product", "Product"),
        ("order", "Order"),
        ("customer", "Customer"),
        ("category", "Category"),
        ("coupon", "Coupon"),
    ]

    name = fields.Char(required=True, default=lambda self: _("Sync Preview"))
    state = fields.Selection(
        [
            ("draft", "Draft"),
            ("done", "Done"),
            ("failed", "Failed"),
        ],
        default="draft",
        required=True,
        index=True,
    )
    source_mode = fields.Selection(SOURCE_SELECTION, required=True, default="import_by_id")
    instance_id = fields.Many2one("woo.instance", string="Woo Instance", required=True, ondelete="cascade")
    record_type = fields.Selection(RECORD_TYPE_SELECTION, required=True, default="product")

    woo_id = fields.Char(string="Woo ID")
    date_filter_type = fields.Selection(
        [
            ("created", "Created Date"),
            ("modified", "Modified Date"),
        ],
        default="created",
    )
    date_from = fields.Date()
    date_to = fields.Date()
    page_size = fields.Integer(default=50)
    update_existing = fields.Boolean(default=True)

    target_model = fields.Char()
    target_id = fields.Integer()

    summary_message = fields.Text(readonly=True)
    total_checked = fields.Integer(readonly=True, default=0)
    would_create_count = fields.Integer(readonly=True, default=0)
    would_update_count = fields.Integer(readonly=True, default=0)
    would_skip_count = fields.Integer(readonly=True, default=0)
    warning_count = fields.Integer(readonly=True, default=0)
    failure_count = fields.Integer(readonly=True, default=0)

    line_ids = fields.One2many("woo.sync.preview.line", "preview_id", string="Preview Lines")

    can_proceed = fields.Boolean(compute="_compute_can_proceed")

    @api.depends("state", "total_checked")
    def _compute_can_proceed(self):
        for rec in self:
            rec.can_proceed = rec.state == "done" and rec.total_checked > 0

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        for rec in records:
            if not rec.name or rec.name == _("Sync Preview"):
                rec.name = _("%(source)s Preview - %(type)s") % {
                    "source": dict(self.SOURCE_SELECTION).get(rec.source_mode, rec.source_mode),
                    "type": dict(self.RECORD_TYPE_SELECTION).get(rec.record_type, rec.record_type),
                }
        return records

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
            raise UserError(_("Unsupported record type for preview: %s") % record_type)
        return endpoint

    def _to_woo_iso(self, value, end_of_day=False):
        if isinstance(value, datetime):
            dt = value
        else:
            date_value = fields.Date.to_date(value)
            if not date_value:
                raise UserError(_("Invalid date in preview date range."))
            dt = datetime.combine(date_value, time.max if end_of_day else time.min)
        return dt.strftime("%Y-%m-%dT%H:%M:%S")

    def _build_date_params(self, page):
        self.ensure_one()
        params = {
            "per_page": int(self.page_size or 50),
            "page": page,
            "orderby": "date",
            "order": "asc",
        }
        from_iso = self._to_woo_iso(self.date_from, end_of_day=False)
        to_iso = self._to_woo_iso(self.date_to, end_of_day=True)
        if self.date_filter_type == "modified":
            params["modified_after"] = from_iso
            params["modified_before"] = to_iso
        else:
            params["after"] = from_iso
            params["before"] = to_iso
        return params

    def _validate_preview_request(self):
        self.ensure_one()
        if not self.instance_id:
            raise UserError(_("Please select Woo Instance."))

        if self.source_mode in ("import_by_id", "manual_record"):
            if not (self.woo_id or "").strip():
                raise UserError(_("Woo ID is required for this preview mode."))

        if self.source_mode == "date_range":
            if not self.date_from or not self.date_to:
                raise UserError(_("Date From and Date To are required for date range preview."))
            if self.date_from > self.date_to:
                raise UserError(_("Date From must not be greater than Date To."))
            if int(self.page_size or 0) <= 0:
                raise UserError(_("Page Size must be greater than 0."))

        if self.source_mode == "manual_record":
            if not self.target_model or not self.target_id:
                raise UserError(_("Manual preview target metadata is missing."))

    def _fetch_payload_by_id(self, woo_id):
        self.ensure_one()
        endpoint = self._api_endpoint_for_type(self.record_type)
        wcapi = self.instance_id._get_wcapi(self.instance_id)
        response = wcapi.get(f"{endpoint}/{woo_id}")
        if response.status_code == 404:
            raise UserError(
                _("%s with Woo ID '%s' was not found in WooCommerce.")
                % (dict(self.RECORD_TYPE_SELECTION).get(self.record_type), woo_id)
            )
        if response.status_code != 200:
            raise UserError(
                _("Failed to fetch preview payload.\nStatus: %s\nResponse: %s")
                % (response.status_code, response.text)
            )
        payload = response.json()
        if not isinstance(payload, dict):
            raise UserError(_("Unexpected WooCommerce response format for preview."))
        return payload

    def _iter_payloads(self):
        self.ensure_one()
        if self.source_mode in ("import_by_id", "manual_record"):
            return [self._fetch_payload_by_id((self.woo_id or "").strip())]

        endpoint = self._api_endpoint_for_type(self.record_type)
        wcapi = self.instance_id._get_wcapi(self.instance_id)
        page = 1
        all_payloads = []
        while True:
            params = self._build_date_params(page)
            response = wcapi.get(endpoint, params=params)
            if response.status_code != 200:
                raise UserError(
                    _("Date range preview fetch failed.\nStatus: %s\nResponse: %s")
                    % (response.status_code, response.text)
                )
            batch = response.json()
            if not isinstance(batch, list):
                raise UserError(_("Unexpected WooCommerce batch format in date range preview."))
            if not batch:
                break
            all_payloads.extend(batch)
            if len(batch) < int(self.page_size or 50):
                break
            page += 1
        return all_payloads

    def _existing_mapping(self, mapping_type, label):
        self.ensure_one()
        return self.instance_id._get_auto_mapping(mapping_type, label)

    def _match_category_preview(self, category_name):
        self.ensure_one()
        normalized = self.instance_id._normalize_mapping_name(category_name)
        if not normalized:
            return False, False, False
        categories = self.env["product.category"].sudo().search([])
        exact = categories.filtered(
            lambda c: self.instance_id._normalize_mapping_name(getattr(c, "name", False)) == normalized
        )
        candidate, warning = self.instance_id._resolve_mapping_candidate(exact, "category", category_name)
        if candidate:
            return candidate, warning, False
        if self.instance_id.auto_create_category_mapping:
            return False, _("Category '%s' would be created for mapping.") % category_name, True
        return False, False, False

    def _match_tag_preview(self, tag_name):
        self.ensure_one()
        if not self.env.registry.get("product.tag"):
            return False, False, False
        normalized = self.instance_id._normalize_mapping_name(tag_name)
        if not normalized:
            return False, False, False
        tags = self.env["product.tag"].sudo().search([])
        exact = tags.filtered(
            lambda t: self.instance_id._normalize_mapping_name(getattr(t, "name", False)) == normalized
        )
        candidate, warning = self.instance_id._resolve_mapping_candidate(exact, "tag", tag_name)
        if candidate:
            return candidate, warning, False
        if self.instance_id.auto_create_tag_mapping:
            return False, _("Tag '%s' would be created for mapping.") % tag_name, True
        return False, False, False

    def _preview_mapping_result(self, payload):
        self.ensure_one()
        data = payload if isinstance(payload, dict) else {}
        if not data or not self.instance_id.auto_mapping_creation:
            return [], False

        messages = []
        would_create_mapping = False

        def _handle_mapping(mapping_type, label, finder):
            nonlocal would_create_mapping
            if not label:
                return
            if self._existing_mapping(mapping_type, label):
                return
            match_data = False
            warning = False
            would_create_related = False
            try:
                result = finder()
                if len(result) == 3:
                    candidate, warning, would_create_related = result
                    match_data = bool(candidate)
                else:
                    match_data, warning = result
            except Exception as exc:
                warning = str(exc)
                match_data = False
            if warning:
                messages.append(warning)
                if self.instance_id.strict_auto_mapping and not match_data and not would_create_related:
                    return
            if match_data or would_create_related:
                would_create_mapping = True
                messages.append(
                    _("Auto mapping would be created for %(type)s '%(label)s'.")
                    % {
                        "type": mapping_type,
                        "label": label,
                    }
                )

        if self.record_type == "order":
            payment_title = data.get("payment_method_title") or data.get("payment_method")
            _handle_mapping(
                "payment_method",
                payment_title,
                lambda: self.instance_id._find_matching_payment(data.get("payment_method"), payment_title),
            )
            for shipping in data.get("shipping_lines", []) or []:
                if isinstance(shipping, dict):
                    shipping_label = shipping.get("method_title") or shipping.get("method_id")
                    _handle_mapping(
                        "shipping_method",
                        shipping_label,
                        lambda s=shipping_label: self.instance_id._find_matching_shipping(s),
                    )
            for tax in data.get("tax_lines", []) or []:
                if isinstance(tax, dict):
                    tax_label = tax.get("label") or tax.get("rate_code")
                    tax_rate = tax.get("rate_percent") or tax.get("rate")
                    _handle_mapping(
                        "tax",
                        tax_label,
                        lambda t=tax_label, r=tax_rate: self.instance_id._find_matching_tax(t, tax_rate=r),
                    )
            status_text = data.get("status")
            _handle_mapping(
                "order_status",
                status_text,
                lambda s=status_text: self.instance_id._find_matching_order_status(s),
            )
        elif self.record_type == "product":
            for category in data.get("categories", []) or []:
                if isinstance(category, dict):
                    name = category.get("name")
                    _handle_mapping(
                        "category",
                        name,
                        lambda n=name: self._match_category_preview(n),
                    )
            for tag in data.get("tags", []) or []:
                if isinstance(tag, dict):
                    name = tag.get("name")
                    _handle_mapping(
                        "tag",
                        name,
                        lambda n=name: self._match_tag_preview(n),
                    )

        return messages, would_create_mapping

    def _find_existing_record(self, payload):
        self.ensure_one()
        instance = self.instance_id
        woo_id = str(payload.get("id") or "")

        if self.record_type == "product":
            direct = self.env["woo.product.sync"].search(
                [("instance_id", "=", instance.id), ("woo_product_id", "=", woo_id)], limit=1
            )
            if direct:
                return {
                    "record": direct,
                    "matched_by": "woo_id",
                    "warning": False,
                    "would_use_sku_match": False,
                }
            product_tmpl = self.env["product.template"].search(
                [
                    ("woo_product_id", "=", woo_id),
                    ("woo_instance_id", "in", [False, instance.id]),
                ],
                limit=1,
            )
            if product_tmpl:
                return {
                    "record": product_tmpl,
                    "matched_by": "woo_id",
                    "warning": False,
                    "would_use_sku_match": False,
                }
            if instance.smart_sku_matching:
                sku = instance._normalize_sku(payload.get("sku") or payload.get("slug"))
                if sku:
                    match_info = instance._find_odoo_product_by_sku(sku, instance=instance)
                    product_tmpl = match_info.get("product_tmpl")
                    if product_tmpl:
                        return {
                            "record": product_tmpl,
                            "matched_by": "sku",
                            "warning": match_info.get("warning") or False,
                            "would_use_sku_match": True,
                        }
                    if match_info.get("warning"):
                        return {
                            "record": False,
                            "matched_by": False,
                            "warning": match_info.get("warning"),
                            "would_use_sku_match": False,
                        }
            return {
                "record": False,
                "matched_by": False,
                "warning": False,
                "would_use_sku_match": False,
            }

        if self.record_type == "order":
            rec = self.env["woo.order.sync"].search(
                [("instance_id", "=", instance.id), ("woo_order_id", "=", woo_id)], limit=1
            )
            if not rec and "woo_order_id" in self.env["sale.order"]._fields:
                rec = self.env["sale.order"].search(
                    [
                        ("woo_order_id", "=", woo_id),
                        ("woo_instance_id", "in", [False, instance.id]),
                    ],
                    limit=1,
                )
            return {"record": rec, "matched_by": "woo_id" if rec else False, "warning": False, "would_use_sku_match": False}

        if self.record_type == "customer":
            rec = self.env["woo.customer.sync"].search(
                [("instance_id", "=", instance.id), ("woo_customer_id", "=", woo_id)], limit=1
            )
            if not rec and "woo_customer_id" in self.env["res.partner"]._fields:
                rec = self.env["res.partner"].search(
                    [
                        ("woo_customer_id", "=", woo_id),
                        ("woo_instance_id", "in", [False, instance.id]),
                    ],
                    limit=1,
                )
            if rec:
                return {"record": rec, "matched_by": "woo_id", "warning": False, "would_use_sku_match": False}
            email = (payload.get("email") or "").strip().lower()
            if email:
                rec = self.env["woo.customer.sync"].search(
                    [("instance_id", "=", instance.id), ("email", "=ilike", email)], limit=1
                )
                if rec:
                    return {"record": rec, "matched_by": "email", "warning": False, "would_use_sku_match": False}
            return {"record": False, "matched_by": False, "warning": False, "would_use_sku_match": False}

        if self.record_type == "category":
            rec = self.env["woo.category.sync"].search(
                [("instance_id", "=", instance.id), ("woo_category_id", "=", woo_id)], limit=1
            )
            if not rec and "woo_category_id" in self.env["product.category"]._fields:
                rec = self.env["product.category"].search(
                    [
                        ("woo_category_id", "=", woo_id),
                        ("woo_instance_id", "in", [False, instance.id]),
                    ],
                    limit=1,
                )
            if rec:
                return {"record": rec, "matched_by": "woo_id", "warning": False, "would_use_sku_match": False}
            name = payload.get("name")
            if name:
                rec = self.env["woo.category.sync"].search(
                    [("instance_id", "=", instance.id), ("name", "=", name)], limit=1
                )
                if rec:
                    return {"record": rec, "matched_by": "name", "warning": False, "would_use_sku_match": False}
            return {"record": False, "matched_by": False, "warning": False, "would_use_sku_match": False}

        if self.record_type == "coupon":
            rec = self.env["woo.coupon.sync"].search(
                [("instance_id", "=", instance.id), ("woo_coupon_id", "=", woo_id)], limit=1
            )
            if rec:
                return {"record": rec, "matched_by": "woo_id", "warning": False, "would_use_sku_match": False}
            code = payload.get("code")
            if code:
                rec = self.env["woo.coupon.sync"].search(
                    [("instance_id", "=", instance.id), ("name", "=", code)], limit=1
                )
                if rec:
                    return {"record": rec, "matched_by": "code", "warning": False, "would_use_sku_match": False}
            return {"record": False, "matched_by": False, "warning": False, "would_use_sku_match": False}

        return {"record": False, "matched_by": False, "warning": False, "would_use_sku_match": False}

    def _payload_summary(self, payload):
        data = payload if isinstance(payload, dict) else {}
        summary = {}
        for key in ("id", "name", "sku", "slug", "number", "status", "email", "code"):
            if key in data and data.get(key) not in (False, None, ""):
                summary[key] = data.get(key)
        if "total" in data:
            summary["total"] = data.get("total")
        return json.dumps(summary, default=str)

    def _line_woo_name(self, payload):
        data = payload if isinstance(payload, dict) else {}
        if self.record_type == "order":
            return data.get("number") or str(data.get("id") or "")
        if self.record_type == "customer":
            first = data.get("first_name") or ""
            last = data.get("last_name") or ""
            return (f"{first} {last}".strip() or data.get("email") or str(data.get("id") or ""))
        if self.record_type == "coupon":
            return data.get("code") or str(data.get("id") or "")
        return data.get("name") or str(data.get("id") or "")

    def _preview_sync_payload(self, payload):
        self.ensure_one()
        if not isinstance(payload, dict):
            return {
                "action_type": "fail",
                "message": _("Payload is not a valid object."),
                "matched_record": False,
                "matched_model": False,
                "matched_res_id": False,
                "would_use_sku_match": False,
                "would_create_mapping": False,
                "would_update_existing": False,
                "warnings": [],
            }

        woo_id = str(payload.get("id") or "").strip()
        if not woo_id:
            return {
                "action_type": "fail",
                "message": _("Woo ID is missing in payload."),
                "matched_record": False,
                "matched_model": False,
                "matched_res_id": False,
                "would_use_sku_match": False,
                "would_create_mapping": False,
                "would_update_existing": False,
                "warnings": [],
            }

        existing = self._find_existing_record(payload)
        warnings = []
        if existing.get("warning"):
            warnings.append(existing.get("warning"))

        mapping_messages, would_create_mapping = self._preview_mapping_result(payload)
        warnings.extend(mapping_messages)

        record = existing.get("record")
        if record and not self.update_existing:
            action_type = "skip"
            message = _("Matching record exists and 'Update existing' is disabled.")
            would_update_existing = False
        elif record:
            action_type = "update"
            message = _("Would update existing record matched by %s.") % (existing.get("matched_by") or "matching")
            would_update_existing = True
        else:
            action_type = "create"
            message = _("Would create new record in Odoo.")
            would_update_existing = False

        return {
            "action_type": action_type,
            "message": message,
            "matched_record": record.display_name if record else False,
            "matched_model": record._name if record else False,
            "matched_res_id": record.id if record else False,
            "would_use_sku_match": bool(existing.get("would_use_sku_match")),
            "would_create_mapping": bool(would_create_mapping),
            "would_update_existing": bool(would_update_existing),
            "warnings": [w for w in warnings if w],
        }

    def _build_summary(self):
        self.ensure_one()
        create_count = self.env["woo.sync.preview.line"].search_count(
            [("preview_id", "=", self.id), ("action_type", "=", "create")]
        )
        update_count = self.env["woo.sync.preview.line"].search_count(
            [("preview_id", "=", self.id), ("action_type", "=", "update")]
        )
        skip_count = self.env["woo.sync.preview.line"].search_count(
            [("preview_id", "=", self.id), ("action_type", "=", "skip")]
        )
        fail_count = self.env["woo.sync.preview.line"].search_count(
            [("preview_id", "=", self.id), ("action_type", "=", "fail")]
        )
        warning_count = self.env["woo.sync.preview.line"].search_count(
            [("preview_id", "=", self.id), ("action_type", "=", "warning")]
        )
        total_checked = create_count + update_count + skip_count + fail_count

        message = _(
            "Preview complete. Checked: %(checked)s | Would Create: %(create)s | "
            "Would Update: %(update)s | Would Skip: %(skip)s | Failures: %(fail)s | Warnings: %(warn)s."
        ) % {
            "checked": total_checked,
            "create": create_count,
            "update": update_count,
            "skip": skip_count,
            "fail": fail_count,
            "warn": warning_count,
        }
        return {
            "total_checked": total_checked,
            "would_create_count": create_count,
            "would_update_count": update_count,
            "would_skip_count": skip_count,
            "failure_count": fail_count,
            "warning_count": warning_count,
            "summary_message": message,
            "state": "done",
        }

    def action_run_preview(self):
        for rec in self:
            rec._validate_preview_request()
            rec.line_ids.unlink()
            payloads = rec._iter_payloads()
            for payload in payloads:
                woo_id = str(payload.get("id") or "") if isinstance(payload, dict) else False
                woo_name = rec._line_woo_name(payload) if isinstance(payload, dict) else _("Unknown")
                try:
                    result = rec._preview_sync_payload(payload)
                    self.env["woo.sync.preview.line"].create(
                        {
                            "preview_id": rec.id,
                            "record_type": rec.record_type,
                            "woo_id": woo_id,
                            "woo_name": woo_name,
                            "action_type": result["action_type"],
                            "matched_record": result["matched_record"] or False,
                            "matched_model": result["matched_model"] or False,
                            "matched_res_id": result["matched_res_id"] or False,
                            "message": result["message"],
                            "would_use_sku_match": result["would_use_sku_match"],
                            "would_create_mapping": result["would_create_mapping"],
                            "would_update_existing": result["would_update_existing"],
                            "payload_summary": rec._payload_summary(payload),
                        }
                    )
                    for warning in result.get("warnings") or []:
                        self.env["woo.sync.preview.line"].create(
                            {
                                "preview_id": rec.id,
                                "record_type": rec.record_type,
                                "woo_id": woo_id,
                                "woo_name": woo_name,
                                "action_type": "warning",
                                "matched_record": result["matched_record"] or False,
                                "matched_model": result["matched_model"] or False,
                                "matched_res_id": result["matched_res_id"] or False,
                                "message": warning,
                                "would_use_sku_match": result["would_use_sku_match"],
                                "would_create_mapping": result["would_create_mapping"],
                                "would_update_existing": result["would_update_existing"],
                                "payload_summary": rec._payload_summary(payload),
                            }
                        )
                except Exception as exc:
                    self.env["woo.sync.preview.line"].create(
                        {
                            "preview_id": rec.id,
                            "record_type": rec.record_type,
                            "woo_id": woo_id,
                            "woo_name": woo_name,
                            "action_type": "fail",
                            "message": str(exc),
                            "payload_summary": rec._payload_summary(payload if isinstance(payload, dict) else {}),
                        }
                    )

            rec.write(rec._build_summary())

        if len(self) == 1:
            return self.action_open_preview()
        return True

    def action_open_preview(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": _("Preview Result"),
            "res_model": "woo.sync.preview",
            "view_mode": "form",
            "res_id": self.id,
            "target": "current",
        }

    def action_proceed_with_actual_sync(self):
        self.ensure_one()
        if self.state != "done":
            raise UserError(_("Run preview before proceeding with actual sync."))

        if self.source_mode == "import_by_id":
            wizard = self.env["woo.import.by.id.wizard"].create(
                {
                    "instance_id": self.instance_id.id,
                    "record_type": self.record_type,
                    "woo_id": self.woo_id,
                    "update_existing": self.update_existing,
                }
            )
            return wizard.action_import_record()

        if self.source_mode == "date_range":
            wizard = self.env["woo.import.date.range.wizard"].create(
                {
                    "instance_id": self.instance_id.id,
                    "record_type": self.record_type,
                    "date_filter_type": self.date_filter_type or "created",
                    "date_from": self.date_from,
                    "date_to": self.date_to,
                    "page_size": self.page_size or 50,
                    "update_existing": self.update_existing,
                }
            )
            return wizard.action_import_date_range()

        if self.source_mode == "manual_record":
            record = self.env[self.target_model].browse(int(self.target_id)).exists()
            if not record:
                raise UserError(_("Target record no longer exists for manual proceed action."))
            if self.target_model == "woo.coupon.sync":
                return record.action_pull_from_woo()
            if not hasattr(record, "action_manual_import_from_woo"):
                raise UserError(_("Manual import method is missing on target model."))
            return record.action_manual_import_from_woo(instance=self.instance_id, via_wizard=True)

        raise UserError(_("Unsupported preview source mode: %s") % self.source_mode)

    @api.model
    def create_and_run_preview(self, vals):
        preview = self.create(vals)
        preview.action_run_preview()
        return preview


class WooSyncPreviewLine(models.Model):
    _name = "woo.sync.preview.line"
    _description = "Woo Sync Preview Line"
    _order = "id asc"

    ACTION_SELECTION = [
        ("create", "Would Create"),
        ("update", "Would Update"),
        ("skip", "Would Skip"),
        ("fail", "Would Fail"),
        ("warning", "Warning"),
    ]

    preview_id = fields.Many2one("woo.sync.preview", required=True, ondelete="cascade", index=True)
    record_type = fields.Selection(WooSyncPreview.RECORD_TYPE_SELECTION, required=True)
    woo_id = fields.Char(index=True)
    woo_name = fields.Char()
    action_type = fields.Selection(ACTION_SELECTION, required=True, index=True)
    matched_record = fields.Char()
    matched_model = fields.Char()
    matched_res_id = fields.Integer()
    message = fields.Text()
    would_use_sku_match = fields.Boolean(default=False)
    would_create_mapping = fields.Boolean(default=False)
    would_update_existing = fields.Boolean(default=False)
    payload_summary = fields.Text()
