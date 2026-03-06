from odoo import models, fields, _
from odoo.exceptions import UserError
from datetime import datetime
import requests
from requests.exceptions import Timeout, RequestException


class WooProductSync(models.Model):
    _name = "woo.product.sync"
    _description = "WooCommerce Product Data"
    _rec_name = "name"
    _order = "synced_on desc"
    _inherit = "woo.sync.engine"

    # --------------------------------------------------
    # BASIC FIELDS
    # --------------------------------------------------
    instance_id = fields.Many2one(
        "woo.instance",
        string="Woo Instance",
        required=True,
        ondelete="cascade",
    )

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
    def _parse_woo_datetime(self, value):
        if not value:
            return False
        try:
            clean = value.replace("Z", "+00:00")
            parsed = datetime.fromisoformat(clean)
            return parsed.replace(tzinfo=None)
        except Exception:
            try:
                return datetime.strptime(
                    value.replace("T", " "), "%Y-%m-%d %H:%M:%S"
                )
            except Exception:
                return False

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

    def _build_stock_payload(self):
        qty = int(self.qty_available or 0)
        stock_status = self.stock_status
        if not stock_status:
            stock_status = "instock" if qty > 0 else "outofstock"

        payload = {
            "manage_stock": bool(self.manage_stock),
            "stock_status": stock_status,
        }

        if self.manage_stock:
            payload["stock_quantity"] = qty

        return payload

    def _push_single_to_woo(self):
        self.ensure_one()

        if not self.instance_id:
            raise UserError(_("Woo instance missing."))

        if not self.woo_product_id:
            raise UserError(_("Woo Product ID missing."))

        wcapi = self.instance_id._get_wcapi(self.instance_id)

        payload = {
            "name": self.name,
            "sku": self.sku,
            "regular_price": str(self.list_price or 0.0),
            "sale_price": str(self.sale_price or 0.0) if self.sale_price else "",
        }
        payload.update(self._build_stock_payload())

        response = wcapi.put(
            f"products/{self.woo_product_id}",
            payload
        )

        if response.status_code != 200:
            raise UserError(response.text)

        data = response.json()
        vals = self._prepare_vals(data)
        vals.update({
            "instance_id": self.instance_id.id,
            "synced_on": fields.Datetime.now(),
        })
        self.write(vals)

    def action_push_to_woo(self):
        for record in self:
            record._push_single_to_woo()

        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("WooCommerce"),
                "message": _("Product pushed to WooCommerce."),
                "type": "success",
            },
        }

    def _pull_single_from_woo(self):
        self.ensure_one()

        if not self.instance_id:
            raise UserError(_("Woo instance missing."))

        if not self.woo_product_id:
            raise UserError(_("Woo Product ID missing."))

        base_url = (self.instance_id.shop_url or "").strip().rstrip("/")
        if not base_url:
            raise UserError(_("Shop URL is not configured."))
        if not base_url.startswith("http"):
            base_url = "https://" + base_url.lstrip("/")

        url = f"{base_url}/wp-json/wc/v3/products/{self.woo_product_id}"
        verify_ssl = not ("localhost" in base_url or "127.0.0.1" in base_url)

        try:
            response = requests.get(
                url,
                auth=(self.instance_id.consumer_key, self.instance_id.consumer_secret),
                timeout=60,
                verify=verify_ssl,
            )
        except Timeout:
            raise UserError(_("WooCommerce request timed out. Please try again."))
        except RequestException as exc:
            raise UserError(_("WooCommerce request failed: %s") % exc)

        if response.status_code != 200:
            raise UserError(response.text)

        data = response.json()
        vals = self._prepare_vals(data)
        vals.update({
            "instance_id": self.instance_id.id,
            "synced_on": fields.Datetime.now(),
        })
        self.write(vals)

    def action_pull_from_woo(self):
        for record in self:
            record._pull_single_from_woo()

        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("WooCommerce"),
                "message": _("Product pulled from WooCommerce."),
                "type": "success",
            },
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
            "published_date": self._parse_woo_datetime(
                p.get("date_created")
            ),
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
