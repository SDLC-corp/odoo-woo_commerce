from odoo import fields, models


class WooAutoMapping(models.Model):
    _name = "woo.auto.mapping"
    _description = "Woo Auto Mapping"
    _order = "write_date desc, id desc"
    _rec_name = "woo_label"
    _woo_auto_mapping_uniq = models.Constraint(
        "unique(instance_id, mapping_type, woo_key)",
        "Woo mapping already exists for this instance/type/key.",
    )

    instance_id = fields.Many2one(
        "woo.instance",
        string="Woo Instance",
        required=True,
        ondelete="cascade",
        index=True,
    )
    mapping_type = fields.Selection(
        [
            ("payment_method", "Payment Method"),
            ("shipping_method", "Shipping Method"),
            ("tax", "Tax"),
            ("category", "Product Category"),
            ("tag", "Product Tag"),
            ("order_status", "Order Status"),
        ],
        required=True,
        index=True,
    )
    woo_key = fields.Char(required=True, index=True)
    woo_label = fields.Char(required=True)

    odoo_model = fields.Char()
    odoo_res_id = fields.Integer()
    odoo_value = fields.Char(string="Mapped Value")
    odoo_display_name = fields.Char(compute="_compute_odoo_display_name", store=False)

    auto_created = fields.Boolean(default=False, index=True)
    active = fields.Boolean(default=True, index=True)
    note = fields.Text()

    def _compute_odoo_display_name(self):
        for rec in self:
            display = rec.odoo_value or ""
            if rec.odoo_model and rec.odoo_res_id:
                try:
                    obj = self.env[rec.odoo_model].browse(rec.odoo_res_id)
                    if obj.exists():
                        display = obj.display_name
                except Exception:
                    pass
            rec.odoo_display_name = display
