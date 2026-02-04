from odoo import models, fields, _
from odoo.exceptions import UserError
import requests
from requests.exceptions import RequestException, Timeout
from woocommerce import API
from datetime import datetime, timedelta
from dateutil.relativedelta import relativedelta
import logging
from datetime import datetime

_logger = logging.getLogger(__name__)


class WooInstance(models.Model):
    _name = "woo.instance"
    _description = "WooCommerce Instance"

    # ------------------------------------------------
    # BASIC CONFIG
    # ------------------------------------------------
    name = fields.Char(required=True)

    shop_url = fields.Char(string="Shop URL", required=True)
    consumer_key = fields.Char(required=True)
    consumer_secret = fields.Char(required=True)
    active = fields.Boolean(default=True)
    wp_username = fields.Char(string="WP Username")
    application_password = fields.Char(string="Application Password")
    webhook_secret = fields.Char(string="Webhook Secret")

    # ------------------------------------------------
    # ANALYTICS SNAPSHOT (PER INSTANCE)
    # ------------------------------------------------
    total_products = fields.Integer(string="Total Products", default=0)
    total_orders = fields.Integer(string="Total Orders", default=0)
    total_customers = fields.Integer(string="Total Customers", default=0)
    total_revenue = fields.Float(string="Total Revenue", default=0.0)
    last_sync = fields.Datetime(string="Last Sync")

    # ------------------------------------------------
    # WEBHOOK AUTO SYNC FLAGS
    # ------------------------------------------------
    webhook_product_create = fields.Boolean()
    webhook_product_update = fields.Boolean()
    webhook_customer_create = fields.Boolean()
    webhook_customer_update = fields.Boolean()
    webhook_order_create = fields.Boolean()
    webhook_order_update = fields.Boolean()
    webhook_category_create = fields.Boolean()
    webhook_category_update = fields.Boolean()
    webhook_giftcard_create = fields.Boolean()
    webhook_giftcard_update = fields.Boolean()

    # ------------------------------------------------
    # CRON FLAGS
    # ------------------------------------------------
    cron_sync_products = fields.Boolean()
    cron_sync_customers = fields.Boolean()
    cron_sync_orders = fields.Boolean()
    cron_sync_categories = fields.Boolean()
    cron_sync_giftcards = fields.Boolean()

    # ------------------------------------------------
    # AUTO SYNC CONFIG (SHOPIFY-LIKE)
    # ------------------------------------------------
    INTERVAL_TYPE = [
        ("hours", "Hourly"),
        ("days", "Daily"),
        ("weeks", "Weekly"),
        ("months", "Monthly"),
    ]

    auto_product_sync = fields.Boolean("Auto Product Sync")
    auto_product_interval_type = fields.Selection(INTERVAL_TYPE, default="hours")
    last_product_sync_at = fields.Datetime()

    auto_customer_sync = fields.Boolean("Auto Customer Sync")
    auto_customer_interval_type = fields.Selection(INTERVAL_TYPE, default="hours")
    last_customer_sync_at = fields.Datetime()

    auto_order_sync = fields.Boolean("Auto Order Sync")
    auto_order_interval_type = fields.Selection(INTERVAL_TYPE, default="hours")
    last_order_sync_at = fields.Datetime()

    auto_category_sync = fields.Boolean("Auto Category Sync")
    auto_category_interval_type = fields.Selection(INTERVAL_TYPE, default="days")
    last_category_sync_at = fields.Datetime()

    auto_coupon_sync = fields.Boolean("Auto Coupon Sync")
    auto_coupon_interval_type = fields.Selection(INTERVAL_TYPE, default="days")
    last_coupon_sync_at = fields.Datetime()

    auto_sync_hour = fields.Selection(
        [(str(i), f"{i:02d}") for i in range(0, 24)], string="Hour", default="0"
    )
    auto_sync_minute = fields.Selection(
        [(str(i), f"{i:02d}") for i in range(0, 60, 5)], string="Minute", default="0"
    )
    auto_sync_weekday = fields.Selection(
        [
            ("0", "Monday"),
            ("1", "Tuesday"),
            ("2", "Wednesday"),
            ("3", "Thursday"),
            ("4", "Friday"),
            ("5", "Saturday"),
            ("6", "Sunday"),
        ],
        string="Weekday",
        default="0",
    )
    auto_sync_month_day = fields.Selection(
        [(str(i), str(i)) for i in range(1, 32)], string="Day of Month", default="1"
    )

    # =================================================
    # INTERNAL HELPERS
    # =================================================
    def _get_wcapi(self, rec):
        return API(
            url=rec.shop_url.rstrip("/"),
            consumer_key=rec.consumer_key,
            consumer_secret=rec.consumer_secret,
            version="wc/v3",
            timeout=30,
        )

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

    def _success_toast(self, title, message):
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": title,
                "message": message,
                "type": "success",
                "sticky": False,
            },
        }

    def fetch_order(self, woo_order_id):
        """
        Fetch a single order from WooCommerce
        """
        self.ensure_one()

        if not self.shop_url or not self.consumer_key or not self.consumer_secret:
            raise UserError("WooCommerce credentials are not configured.")
        base_url = self._get_base_url()
        url = f"{base_url}/wp-json/wc/v3/orders/{woo_order_id}"
        # print("url order 95-",url)

        response = requests.get(
            url,
            auth=(self.consumer_key, self.consumer_secret),
            timeout=30,
            verify=False
        )
        # print("response",response)

        if response.status_code != 200:
            raise UserError(
                f"Failed to fetch Woo order {woo_order_id}: {response.text}"
            )

        return response.json()

    # =================================================
    # TEST CONNECTION
    # =================================================
    def action_test_connection(self):
        for rec in self:
            if not rec.wp_username or not rec.application_password:
                raise UserError(
                    "Please enter WP Username and Application Password."
                )

            url = f"{rec.shop_url.rstrip('/')}/wp-json/wc/v3/system_status"

            try:
                r = requests.get(
                    url,
                    auth=(rec.wp_username, rec.application_password),
                    timeout=20,
                )
            except Exception as e:
                raise UserError(f"Connection error:\n{str(e)}")

            if r.status_code == 200:
                return {
                    "type": "ir.actions.client",
                    "tag": "display_notification",
                    "params": {
                        "title": "Connected",
                        "message": "WooCommerce connection successful.",
                        "type": "success",
                        "sticky": False,
                    },
                }

            raise UserError(
                f"Connection failed\nStatus: {r.status_code}\nResponse:\n{r.text}"
            )

    def auto_sync_all(self, force=True):
        self.ensure_one()

        status = self.env["woo.sync.status"].search(
            [("instance_id", "=", self.id)], limit=1
        )
        if not status:
            status = self.env["woo.sync.status"].create({
                "instance_id": self.id,
            })

        # ⛔ Prevent parallel sync
        if status.syncing:
            return False

        # ⏱ Skip if recently synced (10 min)
        if (
                not force
                and status.last_sync
                and fields.Datetime.now()
                < status.last_sync + timedelta(minutes=10)
        ):
            return False

        # 📝 CREATE AUTO SYNC REPORT (START)
        report = self.env["woo.report"].create({
                "instance_id": self.id,
                "operation": "Auto Sync",
                "status": "running",
                "message": "Auto sync started",
                "auto": True,
                "mode": "cron",
            })

        try:
            status.syncing = True

            # 🔥 RUN ALL SYNC TASKS
            # self.action_sync_products()
            # self.action_sync_categories()
            # self.action_sync_orders()
            if self.cron_sync_products:
                self.action_sync_products()

            if self.cron_sync_categories:
                self.action_sync_categories()

            if self.cron_sync_orders:
                self.action_sync_orders()

            # customers handled via orders

            status.write({
                "last_sync": fields.Datetime.now(),
                "last_error": False,
                "syncing": False,
            })

            # ✅ UPDATE AUTO SYNC REPORT (SUCCESS)
            report.write({
                "status": "success",
                "message": "Auto sync completed successfully",
            })

            return True

        except Exception as e:
            status.write({
                "last_error": str(e),
                "syncing": False,
            })

            # ❌ UPDATE AUTO SYNC REPORT (FAILED)
            report.write({
                "status": "failed",
                "message": str(e),
            })

            raise UserError(str(e))

    def action_sync_products(self):
        self.ensure_one()

        WooProduct = self.env["woo.product.sync"]
        ProductTemplate = self.env["product.template"]

        synced = 0

        try:
            products = self.fetch_products()

            for p in products:
                woo_id = p.get("id")
                if not woo_id:
                    continue

                name = p.get("name")
                sku = p.get("sku") or p.get("slug")

                # -----------------------------------------
                # 1️⃣ FIND OR CREATE PRODUCT
                # -----------------------------------------
                product = ProductTemplate.search(
                    [("default_code", "=", sku)],
                    limit=1
                )

                if not product:
                    product = ProductTemplate.create({
                        "name": name,
                        "default_code": sku,
                        "sale_ok": True,
                        "purchase_ok": True,
                    })

                # -----------------------------------------
                # 2️⃣ APPLY GLOBAL FIELD MAPPING
                # -----------------------------------------
                mapped_vals = self._apply_field_mapping(
                    model="product",
                    woo_data=p,
                    record=product,
                )

                # -----------------------------------------
                # 3️⃣ SAFE FALLBACK
                # -----------------------------------------
                if not mapped_vals:
                    product.write({
                        "name": name,
                        "default_code": sku,
                    })

                _logger.info(
                    "PRODUCT %s | MAPPED VALUES: %s",
                    product.id,
                    mapped_vals,
                )

                # -----------------------------------------
                # 4️⃣ WOO SYNC RECORD
                # -----------------------------------------
                # vals = {
                #     "instance_id": self.id,  # ✅ ADD THIS LINE
                #     "woo_product_id": str(woo_id),
                #     "product_tmpl_id": product.id,
                #     "name": product.name,
                #     "state": "synced",
                #     "synced_on": fields.Datetime.now(),
                # }
                # -----------------------------------------
                # 4️⃣ WOO SYNC RECORD (FULL DATA)
                # -----------------------------------------

                # Categories
                category_ids = []
                for c in p.get("categories", []):
                    category = self.env["product.category"].search(
                        [("name", "=", c.get("name"))],
                        limit=1
                    )
                    if not category:
                        category = self.env["product.category"].create({
                            "name": c.get("name")
                        })
                    category_ids.append(category.id)

                # Tags
                tag_ids = []
                for t in p.get("tags", []):
                    tag = self.env["product.tag"].search(
                        [("name", "=", t.get("name"))],
                        limit=1
                    )
                    if not tag:
                        tag = self.env["product.tag"].create({
                            "name": t.get("name")
                        })
                    tag_ids.append(tag.id)
                published_date = False
                woo_date = p.get("date_created")

                if woo_date:
                    try:
                        published_date = datetime.fromisoformat(
                            woo_date.replace("Z", "+00:00")
                        ).strftime("%Y-%m-%d %H:%M:%S")
                    except Exception:
                        published_date = False

                vals = {
                    "instance_id": self.id,
                    "woo_product_id": str(woo_id),

                    # Identity
                    "product_tmpl_id": product.id,
                    "name": p.get("name"),
                    "sku": sku,

                    # Pricing
                    "list_price": float(p.get("regular_price") or 0.0),
                    "sale_price": float(p.get("sale_price") or 0.0),

                    # Stock
                    "manage_stock": p.get("manage_stock", False),
                    "qty_available": float(p.get("stock_quantity") or 0.0),
                    "stock_status": p.get("stock_status"),

                    # Classification
                    "category_ids": [(6, 0, category_ids)],
                    "tag_ids": [(6, 0, tag_ids)],

                    # Meta
                    "published_date": published_date,
                    "state": "synced",
                    "synced_on": fields.Datetime.now(),
                }

                existing = WooProduct.search(
                    [("woo_product_id", "=", str(woo_id))],
                    limit=1
                )

                if existing:
                    existing.write(vals)
                else:
                    WooProduct.create(vals)

                synced += 1

            self._create_sync_report(
                operation="Product Sync",
                status="success",
                message=f"{synced} products synced successfully",
            )

            return {
                "type": "ir.actions.client",
                "tag": "display_notification",
                "params": {
                    "title": "Products Synced",
                    "message": f"{synced} products synced successfully",
                    "sticky": False,
                },
            }

        except Exception as e:
            self._create_sync_report(
                operation="Product Sync",
                status="failed",
                message=str(e),
            )
            raise UserError(str(e))

    # =================================================
    # SYNC CUSTOMERS
    # =================================================

    def _sync_customer_from_order(self, order):
        """
        Create or update Woo customer from order billing data
        and apply customer field mapping
        """
        WooCustomer = self.env["woo.customer.sync"]

        billing = order.get("billing") or {}
        email = billing.get("email")

        # Skip orders without email
        if not email:
            return False

        # ✅ Always generate a stable woo_customer_id
        customer_id = order.get("customer_id")
        if customer_id and customer_id != 0:
            woo_customer_id = str(customer_id)
        else:
            # Guest checkout fallback
            woo_customer_id = f"guest_{email}"

        vals = {
            "instance_id": self.id,
            "woo_customer_id": woo_customer_id,
            "name": (
                    f"{billing.get('first_name', '')} {billing.get('last_name', '')}".strip()
                    or email
            ),
            "email": email,
            "phone": billing.get("phone"),
            "state": "synced",
            "synced_on": fields.Datetime.now(),
        }

        customer = WooCustomer.search(
            [
                ("woo_customer_id", "=", woo_customer_id),
                ("instance_id", "=", self.id),
            ],
            limit=1,
        )

        if customer:
            customer.write(vals)
        else:
            customer = WooCustomer.create(vals)

        # 🔥 APPLY CUSTOMER FIELD MAPPING (THIS WAS MISSING)
        # Mapping source = Woo order payload
        self._apply_field_mapping(
            model="customer",
            woo_data=order,
            record=customer,
        )

        return customer

    def action_sync_customers(self):
        raise UserError(
            "Customers are synced automatically from Woo orders (guest-safe)."
        )

    def action_sync_orders(self):
        self.ensure_one()
        WooOrder = self.env["woo.order.sync"]
        synced = 0

        try:
            wcapi = self._get_wcapi(self)
            response = wcapi.get("orders", params={"per_page": 100})

            if response.status_code != 200:
                raise UserError(response.text)

            for o in response.json():
                woo_id = o.get("id")
                if not woo_id:
                    continue

                billing = o.get("billing") or {}

                # 🔥 CUSTOMER SYNC (ALREADY GOOD)
                partner = self._sync_customer_from_order(o)

                vals = {
                    "woo_order_id": str(woo_id),
                    "name": o.get("number"),
                    "customer_name": f"{billing.get('first_name', '')} {billing.get('last_name', '')}",
                    "customer_email": billing.get("email"),
                    "total_amount": float(o.get("total", 0.0)),
                    "currency": o.get("currency"),
                    "status": o.get("status"),
                    "payment_method": o.get("payment_method"),
                    "payment_method_title": o.get("payment_method_title"),
                    "date_created": self._parse_woo_datetime(
                        o.get("date_created")
                    ),
                    "state": "synced",
                    "synced_on": fields.Datetime.now(),
                    "instance_id": self.id,
                }

                existing = WooOrder.search(
                    [
                        ("woo_order_id", "=", str(woo_id)),
                        ("instance_id", "=", self.id),
                    ],
                    limit=1
                )

                if existing:
                    existing.write(vals)
                    order_sync = existing
                else:
                    order_sync = WooOrder.create(vals)

                # 🔥 APPLY ORDER FIELD MAPPING (THIS WAS MISSING)
                self._apply_field_mapping(
                    model="order",
                    woo_data=o,
                    record=order_sync,
                )

                # 🔥 ORDER LINES
                order_sync.sync_order_lines(order_sync, o)

                synced += 1

            self._create_sync_report(
                "Order Sync", "success",
                f"{synced} orders synced"
            )

            return self._success_toast(
                "Orders Synced",
                f"{synced} orders synced successfully."
            )

        except Exception as e:
            self._create_sync_report("Order Sync", "failed", str(e))
            raise UserError(str(e))

    # =================================================
    # SYNC CATEGORIES
    # =================================================

    def action_sync_categories(self):
        self.ensure_one()
        WooCategory = self.env["woo.category.sync"]
        synced = 0

        try:
            wcapi = self._get_wcapi(self)
            response = wcapi.get("products/categories", params={"per_page": 100})

            if response.status_code != 200:
                raise UserError(response.text)

            for c in response.json():
                woo_id = c.get("id")
                if not woo_id:
                    continue

                vals = {
                    "name": c.get("name"),
                    "woo_category_id": str(woo_id),
                    "parent_woo_id": str(c.get("parent")) if c.get("parent") else False,
                    "slug": c.get("slug"),
                    "description": c.get("description"),
                    "product_count": c.get("count", 0),
                    "state": "synced",
                    "synced_on": fields.Datetime.now(),
                    "instance_id": self.id,
                }

                existing = WooCategory.search(
                    [
                        ("woo_category_id", "=", str(woo_id)),
                        ("instance_id", "=", self.id),
                    ],
                    limit=1
                )

                if existing:
                    existing.write(vals)
                    category = existing
                else:
                    category = WooCategory.create(vals)

                # 🔥 APPLY CATEGORY FIELD MAPPING (THIS WAS MISSING)
                self._apply_field_mapping(
                    model="category",
                    woo_data=vals,
                    record=category,
                )

                synced += 1

            self._create_sync_report(
                operation="Category Sync",
                status="success",
                message=f"{synced} categories synced successfully",
            )

            return self._success_toast(
                "Categories Synced",
                f"{synced} categories synced successfully."
            )

        except Exception as e:
            self._create_sync_report(
                operation="Category Sync",
                status="failed",
                message=str(e),
            )
            raise UserError(str(e))

    # =================================================
    # SYNC COUPONS
    # =================================================
    def action_sync_coupons(self):
        self.ensure_one()
        WooCoupon = self.env["woo.coupon.sync"]
        synced = 0

        try:
            wcapi = self._get_wcapi(self)
            response = wcapi.get("coupons", params={"per_page": 100})

            if response.status_code != 200:
                raise UserError(response.text)

            for c in response.json():
                woo_id = c.get("id")
                if not woo_id:
                    continue

                vals = {
                    "instance_id": self.id,
                    "name": c.get("code"),
                    "woo_coupon_id": str(woo_id),
                    "discount_type": c.get("discount_type"),
                    "amount": float(c.get("amount") or 0.0),
                    "usage_limit": c.get("usage_limit"),
                    "usage_count": c.get("usage_count"),
                    "expiry_date": self._parse_woo_datetime(c.get("date_expires")),
                    "status": c.get("status"),
                    "state": "synced",
                    "synced_on": fields.Datetime.now(),
                }

                existing = WooCoupon.search(
                    [
                        ("woo_coupon_id", "=", str(woo_id)),
                        ("instance_id", "=", self.id),
                    ],
                    limit=1
                )
                if existing:
                    existing.write(vals)
                else:
                    WooCoupon.create(vals)

                synced += 1

            # ✅ REPORT ENTRY
            self._create_sync_report(
                operation="Coupon Sync",
                status="success",
                message=f"{synced} coupons synced successfully",
            )

            return self._success_toast(
                "Coupons Synced",
                f"{synced} coupons synced successfully."
            )

        except Exception as e:
            # ❌ FAILURE REPORT
            self._create_sync_report(
                operation="Coupon Sync",
                status="failed",
                message=str(e),
            )
            raise UserError(str(e))

    def action_inventory_report(self):
        raise UserError("Inventory report will be implemented next.")

    def action_sync_reports(self):
        """
        Sync WooCommerce Analytics data:
        - Total Orders
        - Total Revenue
        - Total Customers
        - Total Products
        """
        self.ensure_one()

        base_url = self.shop_url.rstrip("/") + "/wp-json/wc/v3"
        auth = (self.consumer_key, self.consumer_secret)

        try:
            # -----------------------------
            # 1️⃣ TOTAL ORDERS
            # -----------------------------
            orders_resp = requests.get(
                f"{base_url}/orders",
                auth=auth,
                params={"per_page": 1},
                timeout=30,
            )
            orders_resp.raise_for_status()
            total_orders = int(orders_resp.headers.get("X-WP-Total", 0))

            # -----------------------------
            # 2️⃣ TOTAL PRODUCTS
            # -----------------------------
            products_resp = requests.get(
                f"{base_url}/products",
                auth=auth,
                params={"per_page": 1},
                timeout=30,
            )
            products_resp.raise_for_status()
            total_products = int(products_resp.headers.get("X-WP-Total", 0))

            # -----------------------------
            # 3️⃣ TOTAL CUSTOMERS
            # -----------------------------
            customers_resp = requests.get(
                f"{base_url}/customers",
                auth=auth,
                params={"per_page": 1},
                timeout=30,
            )
            customers_resp.raise_for_status()
            total_customers = int(customers_resp.headers.get("X-WP-Total", 0))

            # -----------------------------
            # 4️⃣ TOTAL REVENUE
            # -----------------------------
            revenue_resp = requests.get(
                f"{base_url}/reports/sales",
                auth=auth,
                timeout=30,
            )
            revenue_resp.raise_for_status()
            revenue_data = revenue_resp.json()
            total_revenue = float(revenue_data[0].get("total_sales", 0.0)) if revenue_data else 0.0

            # -----------------------------
            # 5️⃣ SAVE LAST SYNC
            # -----------------------------
            self.write({
                "total_orders": total_orders,
                "total_products": total_products,
                "total_customers": total_customers,
                "total_revenue": total_revenue,
                "last_sync": fields.Datetime.now(),
            })

            # -----------------------------
            # 6️⃣ CREATE REPORT LOG
            # -----------------------------
            self._create_sync_report(
                operation="Analytics Sync",
                status="success",
                message=(
                    f"Orders: {total_orders}, "
                    f"Products: {total_products}, "
                    f"Customers: {total_customers}, "
                    f"Revenue: {total_revenue}"
                ),
            )

            # -----------------------------
            # 7️⃣ TOAST MESSAGE
            # -----------------------------
            return {
                "type": "ir.actions.client",
                "tag": "display_notification",
                "params": {
                    "title": _("WooCommerce Analytics"),
                    "message": _("Analytics synced successfully"),
                    "type": "success",
                    "sticky": False,
                },
            }

        except Exception as e:
            # -----------------------------
            # ERROR REPORT
            # -----------------------------
            self._create_sync_report(
                operation="Analytics Sync2",
                status="failed",
                message=str(e),
            )
            raise UserError(_("Analytics sync failed:\n%s") % e)

    def _create_sync_report(self, operation, status, message="", mode="manual", source_action=None, reference=None):
        report = self.env["woo.report"].create({
            "instance_id": self.id,
            "operation": operation,
            "status": status,
            "message": message,
            "mode": mode,
            "source_action": source_action,
            "reference": reference,
        })

        self.env["woo.report.line"].create({
            "report_id": report.id,
            "record_type": operation,
            "source_action": source_action or mode,
            "woo_id": reference or False,
            "name": message or operation,
            "status": "success" if status == "success" else "error",
            "error_message": message if status == "failed" else False,
        })

    def _map_values(self, mappings, woo_data):
        vals = {}

        for mapping in mappings:
            woo_key = mapping.woo_field_key
            odoo_field = mapping.odoo_field_id.name

            # -----------------------------
            # PRICE FALLBACK LOGIC
            # -----------------------------
            if woo_key == "price":
                value = (
                        woo_data.get("sale_price")
                        or woo_data.get("regular_price")
                        or woo_data.get("price")
                )
            else:
                if woo_key not in woo_data:
                    continue
                value = woo_data.get(woo_key)

            if value in (None, "", [], {}):
                continue

            # Convert price fields
            if odoo_field in ("list_price", "standard_price"):
                try:
                    value = float(value)
                except Exception:
                    continue

            # Name safety
            if odoo_field == "name":
                value = str(value)

            vals[odoo_field] = value

        return vals

    def _has_product_specific_mapping(self, product, woo_key, odoo_field):
        Mapping = self.env["woo.field.mapping"]
        return bool(Mapping.search_count([
            ("instance_id", "=", self.id),
            ("model", "=", "product"),
            ("product_tmpl_id", "=", product.id),
            ("woo_field_key", "=", woo_key),
            ("odoo_field_id.name", "=", odoo_field),
            ("active", "=", True),
        ]))

    #     # ------------------------------------------------
    #     # FETCH PRODUCTS (QUERY PARAM AUTH – LOCALHOST SAFE)
    #     # ------------------------------------------------

    def fetch_products(self):
        self.ensure_one()

        if not self.shop_url:
            raise UserError("Shop URL is not configured")

        # url = f"{self.shop_url}/wp-json/wc/v3/products"

        url = "https://localhost/woocommerce/wordpress/wp-json/wc/v3/products"

        response = requests.get(
            url,
            auth=(self.consumer_key, self.consumer_secret),
            timeout=30,
            verify=False,
        )

        # params = {
        #     "consumer_key": self.consumer_key,
        #     "consumer_secret": self.consumer_secret,
        #     "per_page": 100,
        # }
        #
        # response = requests.get(url, params=params, timeout=30)

        if response.status_code == 401:
            raise UserError(
                "Unauthorized (401).\n"
                "Check Woo REST API key permissions (must be READ)."
            )

        response.raise_for_status()
        return response.json()

    def fetch_sample_product(self):
        self.ensure_one()

        base_url = self._get_base_url()
        # url = f"{base_url}/wp-json/wc/v3/products"
        url = "https://localhost/woocommerce/wordpress/wp-json/wc/v3/products"


        response = requests.get(
            url,
            auth=(self.consumer_key, self.consumer_secret),  # ✅ ONLY AUTH METHOD
            timeout=30,
            verify=False,  # ✅ localhost SSL fix
        )

        if response.status_code == 401:
            raise UserError("Woo API Unauthorized (401)")

        response.raise_for_status()
        products = response.json()
        return products[0] if products else {}

    def action_sync_woo_fields(self):
        self.ensure_one()

        WooField = self.env["woo.field"]

        sample = self.fetch_sample_product()
        if not isinstance(sample, dict):
            return

        for key in sample.keys():
            WooField.search([
                ("instance_id", "=", self.id),
                ("name", "=", key),
            ], limit=1) or WooField.create({
                "instance_id": self.id,
                "name": key,
            })

    # def _get_base_url(self):
    #     self.ensure_one()
    #     if not self.shop_url:
    #         raise UserError("Shop URL is not configured")
    #     return self.shop_url.rstrip("/")
    def _get_base_url(self):
        self.ensure_one()

        if not self.shop_url:
            raise UserError("Shop URL is not configured")

        url = self.shop_url.strip().rstrip("/")

        # Force https if missing or http
        if url.startswith("http://"):
            url = url.replace("http://", "https://", 1)

        if not url.startswith("https://"):
            url = "https://" + url.lstrip("/")

        return url

    def _extract_mapped_values(self, woo_data, mappings):
        vals = {}

        for woo_key, odoo_field in mappings.items():
            value = woo_data.get(woo_key)

            if value in (None, "", False):
                continue

            vals[odoo_field] = value

        return vals

    def _get_field_mappings(self, model):
        mappings = self.env["woo.field.mapping"].search([
            ("instance_id", "=", self.id),
            ("model", "=", model),
            ("active", "=", True),
        ])

        return {
            m.woo_field_key.name: m.odoo_field_id.name
            for m in mappings
        }

    def _apply_field_mapping(self, model, woo_data, record):
        mappings = self._get_field_mappings(model)
        vals = {}

        for woo_key, odoo_field in mappings.items():
            # value = woo_data.get(woo_key)
            value = self._get_nested_value(woo_data, woo_key)

            if value not in (None, "", False):
                vals[odoo_field] = value

        if vals:
            record.write(vals)


        return vals

    def fetch_sample_data(self, model):
        self.ensure_one()

        if model == "product":
            return self.fetch_sample_product()

        if model == "order":
            return self.fetch_sample_order()

        if model == "customer":
            return self.fetch_sample_customer()

        if model == "category":
            return self.fetch_sample_category()

        return {}

    def fetch_sample_order(self):
        self.ensure_one()

        base_url = self._get_base_url()
        url = f"{base_url}/wp-json/wc/v3/orders"

        _logger.info("Fetching sample Woo order from %s", url)

        response = requests.get(
            url,
            auth=(self.consumer_key, self.consumer_secret),
            params={"per_page": 1},
            timeout=30,
            verify=False,
        )

        if response.status_code == 401:
            raise UserError("Woo API Unauthorized (401)")

        response.raise_for_status()
        orders = response.json()

        return orders[0] if orders else {}

    def fetch_sample_customer(self):
        self.ensure_one()

        base_url = self._get_base_url()
        url = f"{base_url}/wp-json/wc/v3/customers"

        _logger.info("Fetching sample Woo customer from %s", url)

        response = requests.get(
            url,
            auth=(self.consumer_key, self.consumer_secret),
            params={"per_page": 1},
            timeout=30,
            verify=False,
        )

        if response.status_code == 401:
            raise UserError("Woo API Unauthorized (401)")

        response.raise_for_status()
        customers = response.json()

        return customers[0] if customers else {}

    def fetch_sample_category(self):
        self.ensure_one()
        base_url = self._get_base_url()
        url = f"{base_url}/wp-json/wc/v3/products/categories"


        response = requests.get(
            url,
            auth=(self.consumer_key, self.consumer_secret),
            params={"per_page": 1},
            timeout=30,
            verify=False,
        )

        if response.status_code == 401:
            raise UserError("Woo API Unauthorized (401)")

        response.raise_for_status()
        categories = response.json()

        return categories[0] if categories else {}

    def _get_nested_value(self, data, key):
        """
        Supports nested Woo keys like:
        billing.email
        shipping.first_name
        """
        if not data or not key:
            return None

        value = data
        for part in key.split("."):
            if isinstance(value, dict):
                value = value.get(part)
            else:
                return None
        return value

    def sync_inventory_from_woo(self):
        self.ensure_one()
        Inventory = self.env["woo.inventory"]
        synced = 0

        wcapi = self._get_wcapi(self)
        response = wcapi.get("products", params={"per_page": 100})

        if response.status_code != 200:
            raise UserError(response.text)

        for p in response.json():
            woo_id = str(p.get("id"))

            manage_stock = p.get("manage_stock")
            stock_status = p.get("stock_status")

            if manage_stock:
                quantity = int(p.get("stock_quantity") or 0)
            else:
                quantity = 1 if stock_status == "instock" else 0

            vals = {
                "instance_id": self.id,
                "woo_product_id": woo_id,
                "product_name": p.get("name"),
                "sku": p.get("sku"),
                "quantity": quantity,
            }

            record = Inventory.search(
                [
                    ("woo_product_id", "=", woo_id),
                    ("instance_id", "=", self.id),
                ],
                limit=1,
            )

            if record:
                record.write(vals)
            else:
                Inventory.create(vals)

            synced += 1

        # ✅ SUCCESS POPUP
        return self._success_toast(
            "Inventory Synced",
            f"{synced} products inventory synced successfully"
        )

    def cron_auto_sync_all_instances(self):
        """
        Cron job:
        Automatically sync all active Woo instances
        """
        instances = self.search([
            ("active", "=", True),
        ])

        _logger.info(
            "Woo Cron (auto_sync_all) started for %s instances: %s",
            len(instances),
            ", ".join(instances.mapped("name")) or "none",
        )

        for instance in instances:
            try:
                instance.auto_sync_all(force=False)
            except Exception as e:
                # ❌ NEVER crash cron
                _logger.error(
                    "Woo auto sync failed for instance %s: %s",
                    instance.name,
                    e,
                )

    # =================================================
    # CRON : AUTO SYNC (SHOPIFY-LIKE)
    # =================================================
    def _is_time_to_sync(self, last_sync, interval_type):
        if not last_sync:
            return True

        now = fields.Datetime.now()
        if interval_type == "hours":
            return now >= last_sync + timedelta(hours=1)
        if interval_type == "days":
            return now >= last_sync + timedelta(days=1)
        if interval_type == "weeks":
            return now >= last_sync + timedelta(days=7)
        if interval_type == "months":
            return now >= last_sync + relativedelta(months=1)
        return False

    def cron_auto_sync(self):
        now = fields.Datetime.now()
        instances = self.search([("active", "=", True)])
        _logger.info(
            "Woo Cron (auto_sync) tick for %s instances: %s",
            len(instances),
            ", ".join(instances.mapped("name")) or "none",
        )

        for instance in instances:
            report = False
            executed = []
            try:
                if instance.auto_product_sync and instance._is_time_to_sync(
                    instance.last_product_sync_at,
                    instance.auto_product_interval_type,
                ):
                    if not report:
                        report = self.env["woo.report"].create({
                            "instance_id": instance.id,
                            "operation": "Auto Sync (Cron)",
                            "status": "running",
                            "message": "Auto sync started",
                            "auto": True,
                            "mode": "cron",
                        })
                    instance.action_sync_products()
                    instance.last_product_sync_at = now
                    executed.append("products")

                if instance.auto_customer_sync and instance._is_time_to_sync(
                    instance.last_customer_sync_at,
                    instance.auto_customer_interval_type,
                ):
                    # Customers are derived from orders; re-sync orders.
                    if not report:
                        report = self.env["woo.report"].create({
                            "instance_id": instance.id,
                            "operation": "Auto Sync (Cron)",
                            "status": "running",
                            "message": "Auto sync started",
                            "auto": True,
                            "mode": "cron",
                        })
                    instance.action_sync_orders()
                    instance.last_customer_sync_at = now
                    executed.append("customers")

                if instance.auto_order_sync and instance._is_time_to_sync(
                    instance.last_order_sync_at,
                    instance.auto_order_interval_type,
                ):
                    if not report:
                        report = self.env["woo.report"].create({
                            "instance_id": instance.id,
                            "operation": "Auto Sync (Cron)",
                            "status": "running",
                            "message": "Auto sync started",
                            "auto": True,
                            "mode": "cron",
                        })
                    instance.action_sync_orders()
                    instance.last_order_sync_at = now
                    executed.append("orders")

                if instance.auto_category_sync and instance._is_time_to_sync(
                    instance.last_category_sync_at,
                    instance.auto_category_interval_type,
                ):
                    if not report:
                        report = self.env["woo.report"].create({
                            "instance_id": instance.id,
                            "operation": "Auto Sync (Cron)",
                            "status": "running",
                            "message": "Auto sync started",
                            "auto": True,
                            "mode": "cron",
                        })
                    instance.action_sync_categories()
                    instance.last_category_sync_at = now
                    executed.append("categories")

                if instance.auto_coupon_sync and instance._is_time_to_sync(
                    instance.last_coupon_sync_at,
                    instance.auto_coupon_interval_type,
                ):
                    if not report:
                        report = self.env["woo.report"].create({
                            "instance_id": instance.id,
                            "operation": "Auto Sync (Cron)",
                            "status": "running",
                            "message": "Auto sync started",
                            "auto": True,
                            "mode": "cron",
                        })
                    instance.action_sync_coupons()
                    instance.last_coupon_sync_at = now
                    executed.append("coupons")

                if report:
                    report.write({
                        "status": "success",
                        "message": "Auto sync completed: %s" % ", ".join(executed),
                    })

            except Exception as e:
                _logger.error(
                    "Woo cron auto sync failed for instance %s: %s",
                    instance.name,
                    e,
                )
                if report:
                    report.write({
                        "status": "failed",
                        "message": str(e),
                    })
                else:
                    self.env["woo.report"].create({
                        "instance_id": instance.id,
                        "operation": "Auto Sync (Cron)",
                        "status": "failed",
                        "message": str(e),
                        "auto": True,
                        "mode": "cron",
                    })




