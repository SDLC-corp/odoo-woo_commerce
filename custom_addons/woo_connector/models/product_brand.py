from odoo import _, api, fields, models


class ProductBrand(models.Model):
    _name = "product.brand"
    _description = "Product Brand"
    _rec_name = "name"

    name = fields.Char(
        string="Name",
        required=True,
        help="Brand name as it appears in product listings.",
    )
    display_name = fields.Char(
        string="Display Name",
        compute="_compute_display_name",
        store=True,
        help="Auto-populated from Name. Used wherever Odoo shows a record label "
        "for this brand.",
    )
    active = fields.Boolean(
        string="Active",
        default=True,
        help="Uncheck to archive without deleting.",
    )
    description = fields.Text(
        string="Description",
        help="Optional free-text description shown on brand-related views.",
    )

    @api.depends("name")
    def _compute_display_name(self):
        for rec in self:
            rec.display_name = (rec.name or "").strip() or _("Unnamed Brand")

    def action_save_and_close(self):
        """Persist any pending edits and return to the brand list view."""
        return {
            "type": "ir.actions.act_window",
            "name": _("Product Brands"),
            "res_model": "product.brand",
            "view_mode": "list,form",
            "target": "current",
        }
