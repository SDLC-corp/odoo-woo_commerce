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

    # ------------------------------------------------
    # COMPUTE TARGET ODOO MODEL
    # ------------------------------------------------
    @api.depends("model")
    def _compute_odoo_model(self):
        for rec in self:
            rec.odoo_model_name = {
                "product": "product.template",
                "order": "sale.order",
                "customer": "res.partner",
                "category": "product.category",
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

            rec.woo_preview = str(sample.get(rec.woo_field_key.name, ""))

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

        sample = self.instance_id.fetch_sample_data(self.model)
        value = sample.get(self.woo_field_key.name)

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
