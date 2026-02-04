from odoo import models, fields, api, _
from odoo.exceptions import UserError


class WooCategorySync(models.Model):
    _name = "woo.category.sync"
    _description = "WooCommerce Category Sync"
    _inherit = "woo.sync.engine"
    _rec_name = "name"
    _order = "synced_on desc"

    # --------------------------------------------------
    # CORE FIELDS
    # --------------------------------------------------
    name = fields.Char(required=True)

    woo_category_id = fields.Char(
        string="Woo Category ID",
        index=True,
    )

    parent_woo_id = fields.Char(
        string="Parent Woo Category ID",
        help="WooCommerce parent category ID"
    )

    instance_id = fields.Many2one(
        "woo.instance",
        required=True,
        ondelete="cascade",
    )

    slug = fields.Char()
    description = fields.Text()
    product_count = fields.Integer(string="Woo Product Count")

    state = fields.Selection(
        [
            ("draft", "Draft"),
            ("synced", "Synced"),
            ("failed", "Failed"),
        ],
        default="draft",
        tracking=True,
    )

    synced_on = fields.Datetime()

    # --------------------------------------------------
    # SMART BUTTON
    # --------------------------------------------------
    product_count_odoo = fields.Integer(
        compute="_compute_product_count",
        string="Products",
    )

    # --------------------------------------------------
    # ENGINE HOOKS
    # --------------------------------------------------
    def _woo_endpoint(self):
        return "products/categories"

    def _woo_unique_field(self):
        return "woo_category_id"

    # --------------------------------------------------
    # COMPUTE
    # --------------------------------------------------
    def _compute_product_count(self):
        Product = self.env["product.template"]
        for rec in self:
            rec.product_count_odoo = Product.search_count(
                [("categ_id.name", "=", rec.name)]
            )

    # --------------------------------------------------
    # CREATE / UPDATE CATEGORY IN WOO
    # --------------------------------------------------
    def action_push_to_woo(self):
        """Create or Update category in WooCommerce"""
        self.ensure_one()

        wcapi = self.instance_id._get_wcapi(self.instance_id)

        payload = {
            "name": self.name,
            "slug": self.slug,
            "description": self.description,
        }

        if self.parent_woo_id:
            payload["parent"] = int(self.parent_woo_id)

        # -----------------------------
        # UPDATE
        # -----------------------------
        if self.woo_category_id:
            response = wcapi.put(
                f"products/categories/{self.woo_category_id}",
                payload
            )
        # -----------------------------
        # CREATE
        # -----------------------------
        else:
            response = wcapi.post(
                "products/categories",
                payload
            )

        if response.status_code not in (200, 201):
            raise UserError(response.text)

        data = response.json()

        self.write({
            "woo_category_id": str(data.get("id")),
            "state": "synced",
            "synced_on": fields.Datetime.now(),
        })

        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("WooCommerce"),
                "message": _("Category synced successfully."),
                "type": "success",
            },
        }

    # --------------------------------------------------
    # SMART BUTTON ACTION
    # --------------------------------------------------
    def action_view_products(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": _("Products"),
            "res_model": "product.template",
            "view_mode": "tree,form",
            "domain": [("categ_id.name", "=", self.name)],
        }
