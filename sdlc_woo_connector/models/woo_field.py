from odoo import models, fields


class WooField(models.Model):
    _name = "woo.field"
    _description = "Woo Field"
    _rec_name = "name"
    _order = "name"

    instance_id = fields.Many2one(
        "woo.instance",
        string="Woo Instance",
        required=True,
        ondelete="cascade",
        index=True,
    )

    model = fields.Selection(
        [
            ("product", "Product"),
            ("order", "Order"),
            ("customer", "Customer"),
            ("category", "Category"),
        ],
        string="Model",
        index=True,
    )

    name = fields.Char(
        string="Woo Field Key",
        required=True,
        index=True,
    )

    description = fields.Char(
        string="Description",
    )

    active = fields.Boolean(default=True)

    _sql_constraints = [
        (
            "uniq_field_per_instance_model",
            "unique(instance_id, model, name)",
            "Woo field must be unique per instance and model.",
        )
    ]
