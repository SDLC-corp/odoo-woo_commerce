from odoo import models, fields
import logging

_logger = logging.getLogger(__name__)


class WooWebhookSync(models.AbstractModel):
    _name = "woo.webhook.sync"
    _description = "WooCommerce Webhook Sync"

    def _log_webhook(
            self,
            instance,
            operation,
            status,
            message="",
            source_action=None,
            reference=None,
            payload_data=None,
    ):
        report = False
        try:
            if instance:
                webhook_log_id = self.env.context.get("woo_webhook_log_id")
                report = instance._create_sync_report(
                    operation=operation,
                    status=status,
                    message=message or "",
                    error_message=message if status == "failed" else False,
                    mode="webhook",
                    source_action=source_action or "webhook",
                    reference=reference,
                    sync_direction="import",
                    woo_id=reference,
                    payload_data=payload_data,
                    webhook_log_id=webhook_log_id,
                )
                if webhook_log_id and report:
                    log_rec = self.env["woo.webhook.log"].sudo().browse(webhook_log_id)
                    if log_rec.exists():
                        log_rec.write({"related_report_id": report.id})
        except Exception as e:
            _logger.warning("Failed to log Woo webhook: %s", e)
        return report

    def process_single_import(self, record_type, payload, instance, source_action=None, log_result=False):
        method_map = {
            "product": self.sync_product,
            "order": self.sync_order,
            "customer": self.sync_customer,
            "category": self.sync_category,
            "coupon": self.sync_coupon,
        }
        sync_method = method_map.get(record_type)
        if not sync_method:
            raise ValueError(f"Unsupported record type for single import: {record_type}")
        return sync_method(
            payload,
            instance,
            source_action=source_action or "manual_import_by_id",
            log_result=log_result,
        )

    # -----------------------------
    # PRODUCT
    # -----------------------------
    def sync_product(self, data, instance, source_action=None, log_result=True):
        try:
            ProductTemplate = self.env["product.template"]
            WooProduct = self.env["woo.product.sync"]

            woo_id = data.get("id")
            if not woo_id:
                return

            name = data.get("name")
            sku = instance._normalize_sku(data.get("sku") or data.get("slug"))
            instance._apply_auto_mappings_from_product_payload(data)

            product = ProductTemplate.search(
                [
                    ("woo_product_id", "=", str(woo_id)),
                    ("woo_instance_id", "in", [False, instance.id]),
                ],
                limit=1,
            )
            matched_by_sku = False
            if not product and instance.smart_sku_matching and sku:
                match_info = instance._find_odoo_product_by_sku(sku, instance=instance)
                product = match_info.get("product_tmpl")
                if product:
                    matched_by_sku = True
                    instance._link_product_with_woo_id(product, woo_id, instance=instance)
                    _logger.info(
                        "Product matched by SKU %s and Woo ID %s was linked.",
                        sku,
                        woo_id,
                    )

            if not product:
                product = ProductTemplate.create({
                    "name": name or f"Woo Product {woo_id}",
                    "default_code": sku,
                    "sale_ok": True,
                    "purchase_ok": True,
                })
            instance._link_product_with_woo_id(product, woo_id, instance=instance)

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

            sale_price_raw = data.get("sale_price")
            regular_price_raw = data.get("regular_price")
            # Map WooCommerce fields 1:1 to Odoo fields:
            #   list_price (Regular Price) <- regular_price
            #   sale_price                  <- sale_price (0 if not on sale)
            # Conflating these is BUG-37 and made Sale Price equal Regular Price.
            regular_price_value = float(regular_price_raw or 0.0)
            sale_price_value = (
                float(sale_price_raw)
                if sale_price_raw not in (None, "")
                else 0.0
            )

            vals = {
                "instance_id": instance.id,
                "woo_product_id": str(woo_id),
                "product_tmpl_id": product.id,
                "name": name,
                "sku": sku,
                "list_price": regular_price_value,
                "sale_price": sale_price_value,
                "manage_stock": data.get("manage_stock", False),
                "qty_available": float(data.get("stock_quantity") or 0.0),
                "stock_status": data.get("stock_status"),
                "category_ids": [(6, 0, category_ids)],
                "tag_ids": [(6, 0, tag_ids)],
                "state": "synced",
                "synced_on": fields.Datetime.now(),
            }
            if product:
                write_vals = {
                    "name": name or product.name,
                    "default_code": sku or product.default_code,
                    "list_price": regular_price_value,
                }
                if "sale_price" in product._fields:
                    write_vals["sale_price"] = sale_price_value
                product.write(write_vals)

            existing = WooProduct.search(
                [
                    ("woo_product_id", "=", str(woo_id)),
                    ("instance_id", "=", instance.id),
                ],
                limit=1,
            )
            if existing:
                existing.write(vals)
                sync_record = existing
            else:
                sync_record = WooProduct.create(vals)

            # Apply mapping to Woo sync model fields.
            instance._apply_field_mapping(
                model="product",
                woo_data=data,
                record=sync_record,
            )

            if log_result:
                self._log_webhook(
                    instance,
                    "Webhook Product",
                    "success",
                    (
                        "Product matched by SKU %s and Woo ID %s was linked."
                        % (sku, woo_id)
                    )
                    if matched_by_sku
                    else name,
                    source_action,
                    str(woo_id),
                    payload_data=data,
                )
            return {
                "woo_id": str(woo_id),
                "sku": sku,
                "matched_by": "sku" if matched_by_sku else "woo_id",
                "message": (
                    "Product matched by SKU %s and Woo ID %s was linked."
                    % (sku, woo_id)
                )
                if matched_by_sku
                else False,
            }
        except Exception as e:
            if log_result:
                self._log_webhook(
                    instance,
                    "Webhook Product",
                    "failed",
                    str(e),
                    source_action,
                    str(woo_id),
                    payload_data=data,
                )
            raise

    # -----------------------------
    # CUSTOMER
    # -----------------------------
    def sync_customer(self, data, instance, source_action=None, log_result=True):
        try:
            WooCustomer = self.env["woo.customer.sync"]
            from .woo_customer_sync import (
                PHONE_ALLOWED_RE,
                PHONE_DIGIT_RE,
                PHONE_MIN_DIGITS,
                PHONE_MAX_DIGITS,
                PHONE_MAX_LENGTH,
            )

            woo_id = data.get("id")
            email = (data.get("email") or "").strip().lower()
            first = data.get("first_name") or ""
            last = data.get("last_name") or ""
            name = (f"{first} {last}".strip() or email)

            raw_phone = (
                data.get("billing", {}).get("phone")
                if isinstance(data.get("billing"), dict)
                else data.get("phone")
            )
            phone = (str(raw_phone).strip() if raw_phone else "") or False
            if phone:
                digit_count = len(PHONE_DIGIT_RE.findall(phone))
                if (
                    len(phone) > PHONE_MAX_LENGTH
                    or not PHONE_ALLOWED_RE.match(phone)
                    or digit_count < PHONE_MIN_DIGITS
                    or digit_count > PHONE_MAX_DIGITS
                ):
                    # WooCommerce occasionally returns junk phone values
                    # (``"N/A"``, comments, etc.). Drop those instead of
                    # failing the sync — Woo is the source of truth.
                    phone = False

            vals = {
                "instance_id": instance.id,
                "woo_customer_id": str(woo_id) if woo_id else f"guest_{email}",
                "name": name,
                "email": email,
                "phone": phone,
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
                customer_rec = customer
            else:
                customer_rec = WooCustomer.create(vals)

            instance._apply_field_mapping(
                model="customer",
                woo_data=data,
                record=customer_rec,
            )

            if log_result:
                self._log_webhook(
                    instance,
                    "Webhook Customer",
                    "success",
                    name,
                    source_action,
                    str(woo_id),
                    payload_data=data,
                )
        except Exception as e:
            if log_result:
                self._log_webhook(
                    instance,
                    "Webhook Customer",
                    "failed",
                    str(e),
                    source_action,
                    str(woo_id),
                    payload_data=data,
                )
            raise

    # -----------------------------
    # ORDER
    # -----------------------------
    def sync_order(self, data, instance, source_action=None, log_result=True):
        try:
            WooOrder = self.env["woo.order.sync"]
            woo_id = data.get("id")
            if not woo_id:
                return

            billing = data.get("billing") or {}
            mapping_context = instance._apply_auto_mappings_from_order_payload(data)

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
                "order_state": (mapping_context or {}).get("mapped_order_state") or "draft",
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

            WooOrder._cleanup_duplicates(instance.id)

            # Apply mapping & lines
            instance._apply_field_mapping(
                model="order",
                woo_data=data,
                record=order,
            )
            order.sync_order_lines(order, data)

            if log_result:
                self._log_webhook(
                    instance,
                    "Webhook Order",
                    "success",
                    vals.get("name"),
                    source_action,
                    str(woo_id),
                    payload_data=data,
                )
        except Exception as e:
            if log_result:
                self._log_webhook(
                    instance,
                    "Webhook Order",
                    "failed",
                    str(e),
                    source_action,
                    str(woo_id),
                    payload_data=data,
                )
            raise

    # -----------------------------
    # CATEGORY
    # -----------------------------
    def sync_category(self, data, instance, source_action=None, log_result=True):
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
            if data.get("name"):
                instance._ensure_auto_mapping("category", data.get("name"), payload_data=data)

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

            if log_result:
                self._log_webhook(
                    instance,
                    "Webhook Category",
                    "success",
                    vals.get("name"),
                    source_action,
                    str(woo_id),
                    payload_data=data,
                )
        except Exception as e:
            if log_result:
                self._log_webhook(
                    instance,
                    "Webhook Category",
                    "failed",
                    str(e),
                    source_action,
                    str(woo_id),
                    payload_data=data,
                )
            raise

    # -----------------------------
    # COUPON
    # -----------------------------
    def sync_coupon(self, data, instance, source_action=None, log_result=True):
        try:
            WooCoupon = self.env["woo.coupon.sync"]
            woo_id = data.get("id")
            if not woo_id:
                return

            allowed_types = {"percent", "fixed_cart", "fixed_product"}
            raw_discount_type = (data.get("discount_type") or "").strip().lower()
            discount_type = raw_discount_type if raw_discount_type in allowed_types else False

            vals = {
                "instance_id": instance.id,
                "name": data.get("code"),
                "woo_coupon_id": str(woo_id),
                "discount_type": discount_type,
                "amount": instance._parse_coupon_amount(data.get("amount")),
                "usage_limit": data.get("usage_limit") or 0,
                "usage_count": data.get("usage_count") or 0,
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

            if log_result:
                self._log_webhook(
                    instance,
                    "Webhook Coupon",
                    "success",
                    vals.get("name"),
                    source_action,
                    str(woo_id),
                    payload_data=data,
                )
        except Exception as e:
            if log_result:
                self._log_webhook(
                    instance,
                    "Webhook Coupon",
                    "failed",
                    str(e),
                    source_action,
                    str(woo_id),
                    payload_data=data,
                )
            raise
