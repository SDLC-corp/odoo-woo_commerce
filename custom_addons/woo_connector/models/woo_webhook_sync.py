from odoo import models, fields
import logging

_logger = logging.getLogger(__name__)


class WooWebhookSync(models.AbstractModel):
    _name = "woo.webhook.sync"
    _description = "WooCommerce Webhook Sync"

    def _log_webhook(self, instance, operation, status, message="", source_action=None, reference=None):
        try:
            if instance:
                instance._create_sync_report(
                    operation=operation,
                    status=status,
                    message=message or "",
                    mode="webhook",
                    source_action=source_action or "webhook",
                    reference=reference,
                )
        except Exception as e:
            _logger.warning("Failed to log Woo webhook: %s", e)

    # -----------------------------
    # PRODUCT
    # -----------------------------
    def sync_product(self, data, instance, source_action=None):
        try:
            ProductTemplate = self.env["product.template"]
            WooProduct = self.env["woo.product.sync"]

            woo_id = data.get("id")
            if not woo_id:
                return

            name = data.get("name")
            sku = data.get("sku") or data.get("slug")

            product = ProductTemplate.search(
                [("default_code", "=", sku)], limit=1
            )
            if not product:
                product = ProductTemplate.create({
                    "name": name or f"Woo Product {woo_id}",
                    "default_code": sku,
                    "sale_ok": True,
                    "purchase_ok": True,
                })

            # Apply field mapping if configured
            instance._apply_field_mapping(
                model="product",
                woo_data=data,
                record=product,
            )

            # Categories
            category_ids = []
            for c in data.get("categories", []):
                category = self.env["product.category"].search(
                    [("name", "=", c.get("name"))],
                    limit=1,
                )
                if not category:
                    category = self.env["product.category"].create({
                        "name": c.get("name"),
                    })
                category_ids.append(category.id)

            # Tags
            tag_ids = []
            for t in data.get("tags", []):
                tag = self.env["product.tag"].search(
                    [("name", "=", t.get("name"))],
                    limit=1,
                )
                if not tag:
                    tag = self.env["product.tag"].create({
                        "name": t.get("name"),
                    })
                tag_ids.append(tag.id)

            vals = {
                "instance_id": instance.id,
                "woo_product_id": str(woo_id),
                "product_tmpl_id": product.id,
                "name": name,
                "sku": sku,
                "list_price": float(data.get("regular_price") or 0.0),
                "sale_price": float(data.get("sale_price") or 0.0),
                "manage_stock": data.get("manage_stock", False),
                "qty_available": float(data.get("stock_quantity") or 0.0),
                "stock_status": data.get("stock_status"),
                "category_ids": [(6, 0, category_ids)],
                "tag_ids": [(6, 0, tag_ids)],
                "state": "synced",
                "synced_on": fields.Datetime.now(),
            }

            existing = WooProduct.search(
                [
                    ("woo_product_id", "=", str(woo_id)),
                    ("instance_id", "=", instance.id),
                ],
                limit=1,
            )
            if existing:
                existing.write(vals)
            else:
                WooProduct.create(vals)

            self._log_webhook(instance, "Webhook Product", "success", name, source_action, str(woo_id))
        except Exception as e:
            self._log_webhook(instance, "Webhook Product", "failed", str(e), source_action, str(woo_id))
            raise

    # -----------------------------
    # CUSTOMER
    # -----------------------------
    def sync_customer(self, data, instance, source_action=None):
        try:
            WooCustomer = self.env["woo.customer.sync"]

            woo_id = data.get("id")
            email = data.get("email")
            first = data.get("first_name") or ""
            last = data.get("last_name") or ""
            name = (f"{first} {last}".strip() or email)

            vals = {
                "instance_id": instance.id,
                "woo_customer_id": str(woo_id) if woo_id else f"guest_{email}",
                "name": name,
                "email": email,
                "phone": data.get("billing", {}).get("phone") if isinstance(data.get("billing"), dict) else data.get("phone"),
                "state": "synced",
                "synced_on": fields.Datetime.now(),
            }

            customer = WooCustomer.search(
                [
                    ("woo_customer_id", "=", vals["woo_customer_id"]),
                    ("instance_id", "=", instance.id),
                ],
                limit=1,
            )
            if customer:
                customer.write(vals)
            else:
                WooCustomer.create(vals)

            self._log_webhook(instance, "Webhook Customer", "success", name, source_action, str(woo_id))
        except Exception as e:
            self._log_webhook(instance, "Webhook Customer", "failed", str(e), source_action, str(woo_id))
            raise

    # -----------------------------
    # ORDER
    # -----------------------------
    def sync_order(self, data, instance, source_action=None):
        try:
            WooOrder = self.env["woo.order.sync"]
            woo_id = data.get("id")
            if not woo_id:
                return

            billing = data.get("billing") or {}

            # Sync customer from order payload
            instance._sync_customer_from_order(data)

            vals = {
                "woo_order_id": str(woo_id),
                "name": data.get("number"),
                "customer_name": f"{billing.get('first_name', '')} {billing.get('last_name', '')}",
                "customer_email": billing.get("email"),
                "total_amount": float(data.get("total", 0.0)),
                "currency": data.get("currency"),
                "status": data.get("status"),
                "payment_method": data.get("payment_method"),
                "payment_method_title": data.get("payment_method_title"),
                "date_created": instance._parse_woo_datetime(data.get("date_created")),
                "state": "synced",
                "synced_on": fields.Datetime.now(),
                "instance_id": instance.id,
            }

            order = WooOrder.search(
                [
                    ("woo_order_id", "=", str(woo_id)),
                    ("instance_id", "=", instance.id),
                ],
                limit=1,
            )
            if order:
                order.write(vals)
            else:
                order = WooOrder.create(vals)

            # Apply mapping & lines
            instance._apply_field_mapping(
                model="order",
                woo_data=data,
                record=order,
            )
            order.sync_order_lines(order, data)

            self._log_webhook(instance, "Webhook Order", "success", vals.get("name"), source_action, str(woo_id))
        except Exception as e:
            self._log_webhook(instance, "Webhook Order", "failed", str(e), source_action, str(woo_id))
            raise

    # -----------------------------
    # CATEGORY
    # -----------------------------
    def sync_category(self, data, instance, source_action=None):
        try:
            WooCategory = self.env["woo.category.sync"]
            woo_id = data.get("id")
            if not woo_id:
                return

            vals = {
                "name": data.get("name"),
                "woo_category_id": str(woo_id),
                "parent_woo_id": str(data.get("parent")) if data.get("parent") else False,
                "slug": data.get("slug"),
                "description": data.get("description"),
                "product_count": data.get("count", 0),
                "state": "synced",
                "synced_on": fields.Datetime.now(),
                "instance_id": instance.id,
            }

            existing = WooCategory.search(
                [
                    ("woo_category_id", "=", str(woo_id)),
                    ("instance_id", "=", instance.id),
                ],
                limit=1,
            )
            if existing:
                existing.write(vals)
            else:
                WooCategory.create(vals)

            self._log_webhook(instance, "Webhook Category", "success", vals.get("name"), source_action, str(woo_id))
        except Exception as e:
            self._log_webhook(instance, "Webhook Category", "failed", str(e), source_action, str(woo_id))
            raise

    # -----------------------------
    # COUPON
    # -----------------------------
    def sync_coupon(self, data, instance, source_action=None):
        try:
            WooCoupon = self.env["woo.coupon.sync"]
            woo_id = data.get("id")
            if not woo_id:
                return

            vals = {
                "instance_id": instance.id,
                "name": data.get("code"),
                "woo_coupon_id": str(woo_id),
                "discount_type": data.get("discount_type"),
                "amount": float(data.get("amount") or 0.0),
                "usage_limit": data.get("usage_limit"),
                "usage_count": data.get("usage_count"),
                "expiry_date": instance._parse_woo_datetime(data.get("date_expires")),
                "status": data.get("status"),
                "state": "synced",
                "synced_on": fields.Datetime.now(),
            }

            existing = WooCoupon.search(
                [
                    ("woo_coupon_id", "=", str(woo_id)),
                    ("instance_id", "=", instance.id),
                ],
                limit=1,
            )
            if existing:
                existing.write(vals)
            else:
                WooCoupon.create(vals)

            self._log_webhook(instance, "Webhook Coupon", "success", vals.get("name"), source_action, str(woo_id))
        except Exception as e:
            self._log_webhook(instance, "Webhook Coupon", "failed", str(e), source_action, str(woo_id))
            raise
