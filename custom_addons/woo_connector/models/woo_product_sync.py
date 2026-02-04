from odoo import models, fields, _
from odoo.exceptions import UserError


class WooProductSync(models.Model):
    _name = "woo.product.sync"
    _description = "WooCommerce Product Data"
    _rec_name = "name"
    _order = "synced_on desc"
    _inherit = "woo.sync.engine"

    # --------------------------------------------------
    # BASIC FIELDS
    # --------------------------------------------------
    name = fields.Char(string="Product Name", required=True)
    sku = fields.Char(string="SKU")
    woo_product_id = fields.Char(string="Woo Product ID")
    synced_on = fields.Datetime(string="Synced On")

    state = fields.Selection(
        [
            ("synced", "Synced"),
            ("failed", "Failed"),
        ],
        string="Status",
        default="synced",
        required=True,
    )

    product_tmpl_id = fields.Many2one(
        comodel_name="product.template",
        string="Odoo Product",
        ondelete="set null",
    )

    # -----------------------------
    # PRICING
    # -----------------------------
    list_price = fields.Float(string="Regular Price")
    sale_price = fields.Float(string="Sale Price")

    # -----------------------------
    # STOCK
    # -----------------------------
    manage_stock = fields.Boolean(string="Manage Stock")
    qty_available = fields.Float(string="Stock Qty")
    stock_status = fields.Selection(
        [
            ("instock", "In Stock"),
            ("outofstock", "Out of Stock"),
        ],
        string="Stock Status",
    )

    # -----------------------------
    # CLASSIFICATION
    # -----------------------------
    category_ids = fields.Many2many(
        "product.category",
        string="Categories",
    )

    tag_ids = fields.Many2many(
        "product.tag",
        string="Tags",
    )

    brand_id = fields.Many2one(
        "product.brand",
        string="Brand",
    )

    # -----------------------------
    # PUBLISHING
    # -----------------------------
    published_date = fields.Datetime(string="Published On")

    # --------------------------------------------------
    # SMART BUTTON ACTION
    # --------------------------------------------------
    def action_open_in_woocommerce(self):
        self.ensure_one()

        if not self.woo_product_id:
            raise UserError(_("WooCommerce Product ID not found."))

        instance = self.env["woo.instance"].search(
            [("shop_url", "!=", False)],
            limit=1,
        )

        if not instance:
            raise UserError(_("WooCommerce instance not configured."))

        base_url = instance.shop_url.rstrip("/")
        url = f"{base_url}/?post_type=product&p={self.woo_product_id}"
        print("print",url)

        return {
            "type": "ir.actions.act_url",
            "url": url,
            "target": "new",
        }

    def _woo_endpoint(self):
        return "products"

    def _woo_unique_field(self):
        return "woo_product_id"

    # def _prepare_vals(self, p):
    #     sku = p.get("sku") or p.get("slug")
    #
    #     product = self.env["product.template"].search(
    #         [("default_code", "=", sku)], limit=1
    #     )
    #
    #     if not product:
    #         product = self.env["product.template"].create({
    #             "name": p.get("name"),
    #             "default_code": sku,
    #             "sale_ok": True,
    #             "purchase_ok": True,
    #         })
    #
    #     return {
    #         "woo_product_id": str(p["id"]),
    #         "name": p.get("name"),
    #         "sku": sku,
    #         "product_tmpl_id": product.id,
    #     }
    def _prepare_vals(self, p):
        sku = p.get("sku") or p.get("slug")

        ProductTmpl = self.env["product.template"]
        Category = self.env["product.category"]
        Tag = self.env["product.tag"]

        # -----------------------------
        # PRODUCT TEMPLATE
        # -----------------------------
        product = ProductTmpl.search(
            [("default_code", "=", sku)],
            limit=1
        )

        if not product:
            product = ProductTmpl.create({
                "name": p.get("name"),
                "default_code": sku,
                "sale_ok": True,
                "purchase_ok": True,
                "list_price": float(p.get("regular_price") or 0.0),
            })

        # -----------------------------
        # CATEGORIES
        # -----------------------------
        category_ids = []
        for c in p.get("categories", []):
            category = Category.search(
                [("name", "=", c.get("name"))],
                limit=1
            )
            if not category:
                category = Category.create({
                    "name": c.get("name")
                })
            category_ids.append(category.id)

        # -----------------------------
        # TAGS
        # -----------------------------
        tag_ids = []
        for t in p.get("tags", []):
            tag = Tag.search(
                [("name", "=", t.get("name"))],
                limit=1
            )
            if not tag:
                tag = Tag.create({
                    "name": t.get("name")
                })
            tag_ids.append(tag.id)

        # -----------------------------
        # STOCK
        # -----------------------------
        manage_stock = p.get("manage_stock", False)
        qty = float(p.get("stock_quantity") or 0.0)

        return {
            "woo_product_id": str(p.get("id")),
            "name": p.get("name"),
            "sku": sku,
            "product_tmpl_id": product.id,

            # Pricing
            "list_price": float(p.get("regular_price") or 0.0),
            "sale_price": float(p.get("sale_price") or 0.0),

            # Stock
            "manage_stock": manage_stock,
            "qty_available": qty,
            "stock_status": p.get("stock_status"),

            # Classification
            "category_ids": [(6, 0, category_ids)],
            "tag_ids": [(6, 0, tag_ids)],

            # Meta
            "state": "synced",
            "published_date": p.get("date_created"),
            "synced_on": fields.Datetime.now(),
        }

    def action_sync_products(self):
        self.ensure_one()

        products = self.instance_id.fetch_products()

        mappings = self.env["woo.field.mapping"].search([
            ("instance_id", "=", self.instance_id.id),
            ("model", "=", "product"),
            ("active", "=", True),
        ])

        Product = self.env["product.product"]

        for woo in products:
            vals = {}

            for m in mappings:
                if m.woo_field in woo:
                    vals[m.odoo_field] = woo[m.woo_field]

            if not vals:
                continue

            product = Product.search(
                [("default_code", "=", woo.get("sku"))], limit=1
            )

            if product:
                product.write(vals)
            else:
                Product.create(vals)

    def action_open_odoo_product(self):
        self.ensure_one()

        if not self.product_tmpl_id:
            raise UserError(_("No linked Odoo Product found."))

        return {
            "type": "ir.actions.act_window",
            "name": "Product",
            "res_model": "product.template",
            "view_mode": "form",
            "res_id": self.product_tmpl_id.id,  # ⭐ THIS PREVENTS /new
            "target": "current",
        }

    def action_create_odoo_product(self):
        return {
            "type": "ir.actions.act_window",
            "name": "New Product",
            "res_model": "product.template",
            "view_mode": "form",
            "target": "current",
            "context": {
                "default_type": "product",
            },
        }

    def action_open_odoo_product(self):
        self.ensure_one()

        return {
            "type": "ir.actions.act_window",
            "name": "Product",
            "res_model": "product.template",
            "view_mode": "form",
            "target": "current",
            "context": {
                "default_woo_instance_id": self.instance_id.id,
                "default_name": self.name,
                "default_default_code": self.sku,
            },
        }
