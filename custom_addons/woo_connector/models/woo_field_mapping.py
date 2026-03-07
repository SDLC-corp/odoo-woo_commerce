from odoo import models, fields, api
from odoo.exceptions import UserError


class WooFieldMapping(models.Model):
    _name = "woo.field.mapping"
    _description = "Woo Field Mapping"
    _rec_name = "odoo_field_id"

    # ------------------------------------------------
    # CORE CONFIG
    # ------------------------------------------------
    instance_id = fields.Many2one(
        "woo.instance",
        string="Woo Instance",
        required=True,
        ondelete="cascade",
    )

    model = fields.Selection(
        [
            ("product", "Product"),
            ("order", "Order"),
            ("customer", "Customer"),
            ("category", "Category"),
        ],
        required=True,
        default="product",
    )

    active = fields.Boolean(default=True)

    # (kept for future, ignored for now)
    product_tmpl_id = fields.Many2one(
        "product.template",
        string="Product (Optional)",
        help="Leave empty for global mapping.",
    )

    # ------------------------------------------------
    # ODOO FIELD (DYNAMIC DOMAIN)
    # ------------------------------------------------
    odoo_field_id = fields.Many2one(
        "ir.model.fields",
        string="Odoo Field",
        required=True,
        ondelete="cascade",
        domain="[('model', '=', odoo_model_name), ('store', '=', True)]",
    )

    odoo_model_name = fields.Char(
        compute="_compute_odoo_model",
        store=True,
    )

    # ------------------------------------------------
    # WOO FIELD
    # ------------------------------------------------
    woo_field_key = fields.Many2one(
        "woo.field",
        string="Woo Field",
        required=True,
        domain="[('instance_id', '=', instance_id), ('active', '=', True)]",
    )

    # ------------------------------------------------
    # PREVIEW
    # ------------------------------------------------
    woo_preview = fields.Char(
        compute="_compute_preview",
        readonly=True,
    )

    odoo_preview = fields.Char(
        compute="_compute_preview",
        readonly=True,
    )

    def _flatten_woo_keys(self, payload, prefix=""):
        keys = set()
        if not isinstance(payload, dict):
            return keys

        for key, value in payload.items():
            if not key:
                continue
            full_key = f"{prefix}.{key}" if prefix else str(key)
            keys.add(full_key)
            if isinstance(value, dict):
                keys |= self._flatten_woo_keys(value, full_key)
        return keys

    def _default_model_keys(self, model_name):
        defaults = {
            "product": {
                "id", "name", "sku", "slug", "status", "regular_price",
                "sale_price", "stock_quantity", "stock_status", "manage_stock",
                "description", "short_description", "date_created",
            },
            "order": {
                "id", "number", "status", "currency", "total", "customer_id",
                "payment_method", "payment_method_title", "date_created",
                "billing.email", "billing.phone", "billing.first_name", "billing.last_name",
            },
            "customer": {
                "id", "email", "first_name", "last_name", "username",
                "date_created", "billing.phone", "billing.email",
            },
            "category": {
                "id", "name", "slug", "parent", "count", "description",
            },
        }
        return defaults.get(model_name, set())

    def _ensure_woo_fields_catalog(self):
        self.ensure_one()
        if not self.instance_id or not self.model:
            return

        WooField = self.env["woo.field"]
        keys = set()
        try:
            sample = self.instance_id.fetch_sample_data(self.model)
            keys |= self._flatten_woo_keys(sample)
        except Exception:
            # Keep UX usable even when sample API is unavailable.
            pass

        keys |= self._default_model_keys(self.model)

        for key in sorted(k for k in keys if k):
            WooField.search(
                [("instance_id", "=", self.instance_id.id), ("name", "=", key)],
                limit=1,
            ) or WooField.create({
                "instance_id": self.instance_id.id,
                "name": key,
                "active": True,
            })

    @api.onchange("instance_id", "model")
    def _onchange_instance_or_model(self):
        for rec in self:
            rec.woo_field_key = False
            if rec.instance_id and rec.model:
                rec._ensure_woo_fields_catalog()

    # ------------------------------------------------
    # COMPUTE TARGET ODOO MODEL
    # ------------------------------------------------
    @api.depends("model")
    def _compute_odoo_model(self):
        for rec in self:
            rec.odoo_model_name = {
                "product": "woo.product.sync",
                "order": "woo.order.sync",
                "customer": "woo.customer.sync",
                "category": "woo.category.sync",
            }.get(rec.model)

    # ------------------------------------------------
    # PREVIEW COMPUTE
    # ------------------------------------------------
    @api.depends("woo_field_key", "odoo_field_id", "instance_id", "model")
    def _compute_preview(self):
        for rec in self:
            rec.woo_preview = ""
            rec.odoo_preview = ""

            if not rec.instance_id or not rec.woo_field_key:
                continue

            try:
                sample = rec.instance_id.fetch_sample_data(rec.model)
            except Exception:
                continue

            rec.woo_preview = str(
                rec.instance_id._get_nested_value(sample, rec.woo_field_key.name) or ""
            )

            if rec.odoo_field_id:
                model = self.env[rec.odoo_model_name]
                record = model.search([], limit=1)
                if record:
                    rec.odoo_preview = str(
                        getattr(record, rec.odoo_field_id.name, "")
                    )

    # ------------------------------------------------
    # TEST BUTTON
    # ------------------------------------------------
    def action_test_mapping(self):
        self.ensure_one()

        try:
            sample = self.instance_id.fetch_sample_data(self.model)
        except Exception as e:
            raise UserError(
                "Unable to fetch sample data from WooCommerce.\n"
                "Check Shop URL/protocol (http vs https) and credentials.\n\n"
                f"Details: {e}"
            )

        value = self.instance_id._get_nested_value(sample, self.woo_field_key.name)

        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": "Mapping OK",
                "message": (
                    f"Model: {self.model}\n"
                    f"Woo → {self.woo_field_key.name} = {value}\n"
                    f"Odoo → {self.odoo_field_id.name}"
                ),
                "sticky": False,
            },
        }

    def action_load_woo_fields(self):
        self.ensure_one()
        if not self.instance_id:
            raise UserError("Please select Woo Instance first.")
        if not self.model:
            raise UserError("Please select model first.")

        self._ensure_woo_fields_catalog()
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": "Woo Fields",
                "message": "Woo field dropdown refreshed.",
                "type": "success",
                "sticky": False,
            },
        }
