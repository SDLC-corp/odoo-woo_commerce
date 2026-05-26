from odoo import models, api, fields
from odoo.exceptions import UserError
import requests
from datetime import datetime, timedelta, time
import json
import logging

_logger = logging.getLogger(__name__)


class WooDashboard(models.AbstractModel):
    _name = "woo.dashboard"
    _description = "WooCommerce Dashboard"
    _auto = False

    def _get_active_instances(self):
        return self.env["woo.instance"].search([("active", "=", True)])

    def _get_instance_or_raise(self, instance_id=None):
        if instance_id:
            instance = self.env["woo.instance"].browse(int(instance_id))
            if not instance or not instance.exists():
                raise UserError("WooCommerce instance not found.")
            return instance
        instance = self._get_active_instances()[:1]
        if not instance:
            raise UserError("No active WooCommerce instance found.")
        return instance

    def _fetch_json(self, url, auth, params=None):
        try:
            r = requests.get(url, auth=auth, params=params or {}, timeout=8)
            r.raise_for_status()
            return r.json()
        except Exception:
            return {}

    def _instance_fetch_json(self, instance, endpoint, params=None, timeout=6):
        base = instance._get_base_url().rstrip("/")
        url = f"{base}/{endpoint.lstrip('/')}"
        try:
            response = instance._woo_get(url, params=params or {}, timeout=timeout)
            if response.status_code != 200:
                _logger.warning(
                    "Woo request failed for %s on %s (status %s).",
                    endpoint,
                    instance.display_name,
                    response.status_code,
                )
                return {}
            payload = response.json()
            return payload if isinstance(payload, (dict, list)) else {}
        except Exception as exc:
            _logger.warning(
                "Woo request failed for %s on %s: %s",
                endpoint,
                instance.display_name,
                exc,
            )
            return {}

    def _instance_total_from_header(self, instance, endpoint):
        base = instance._get_base_url().rstrip("/")
        url = f"{base}/wp-json/wc/v3/{endpoint}"
        try:
            response = instance._woo_get(url, params={"per_page": 1}, timeout=4)
        except Exception as exc:
            _logger.warning(
                "Woo totals request failed for %s on %s: %s",
                endpoint,
                instance.display_name,
                exc,
            )
            return 0

        if response.status_code != 200:
            _logger.warning(
                "Woo totals request failed for %s on %s (status %s).",
                endpoint,
                instance.display_name,
                response.status_code,
            )
            return 0
        return int(response.headers.get("X-WP-Total", 0) or 0)

    def _total_from_header(self, base, auth_candidates, endpoint):
        tried = set()
        for auth in auth_candidates:
            if not auth or not all(auth):
                continue
            auth_key = tuple(auth)
            if auth_key in tried:
                continue
            tried.add(auth_key)
            try:
                r = requests.get(
                    f"{base}/wp-json/wc/v3/{endpoint}",
                    auth=auth,
                    params={"per_page": 1},
                    timeout=6,
                )
            except Exception as exc:
                _logger.warning(
                    "Woo totals request failed for %s: %s",
                    endpoint,
                    exc,
                )
                continue

            if r.status_code == 200:
                return int(r.headers.get("X-WP-Total", 0))

            _logger.warning(
                "Woo totals request failed for %s (status %s).",
                endpoint,
                r.status_code,
            )
        return 0

    def _customer_count_from_orders(self, instances, date_from=None, date_to=None):
        """Distinct customer email count from orders in the given window.

        Used only as a fallback when the dedicated ``woo.customer.sync`` table
        is empty. Prefer ``_customer_count`` for the actual KPI value.
        """
        if not instances:
            return 0
        Order = self.env["woo.order.sync"]
        domain = [
            ("instance_id", "in", instances.ids),
            ("customer_email", "!=", False),
            ("customer_email", "!=", ""),
        ]
        if date_from and date_to:
            domain += [
                ("date_created", ">=", date_from),
                ("date_created", "<=", date_to),
            ]
        groups = Order._read_group(domain, groupby=["customer_email"])
        return sum(1 for group in groups if group and group[0])

    def _customer_count(self, instances, date_from=None, date_to=None):
        """Actual customer count for the dashboard KPI card.

        Counts records on ``woo.customer.sync`` directly. Falls back to
        distinct order emails when the customer table is empty so the card
        is not stuck at zero on a fresh import.
        """
        if not instances:
            return 0
        Customer = self.env["woo.customer.sync"]
        domain = [("instance_id", "in", instances.ids)]
        if date_from and date_to:
            domain += [
                ("synced_on", ">=", date_from),
                ("synced_on", "<=", date_to),
            ]
        count = Customer.search_count(domain)
        if count:
            return count
        # No customer.sync rows for this window — derive from order emails.
        return self._customer_count_from_orders(
            instances, date_from=date_from, date_to=date_to
        )

    def _totals_from_snapshots(self, instances):
        if not instances:
            return {
                "products": 0,
                "orders": 0,
                "customers": 0,
                "categories": 0,
                "coupons": 0,
                "total_sales": 0.0,
                "net_sales": 0.0,
            }

        return {
            "products": sum(instances.mapped("total_products")),
            "orders": sum(instances.mapped("total_orders")),
            "customers": sum(instances.mapped("total_customers")),
            "categories": 0,
            "coupons": 0,
            "total_sales": sum(instances.mapped("total_revenue")),
            "net_sales": sum(instances.mapped("total_revenue")),
        }

    def _totals_from_local_sync(self, instances, date_from=None, date_to=None):
        if not instances:
            return {
                "products": 0,
                "orders": 0,
                "customers": 0,
                "categories": 0,
                "coupons": 0,
                "total_sales": 0.0,
                "net_sales": 0.0,
            }

        Product = self.env["woo.product.sync"]
        Order = self.env["woo.order.sync"]
        Category = self.env["woo.category.sync"]
        Coupon = self.env["woo.coupon.sync"]

        product_domain = [("instance_id", "in", instances.ids)]
        order_domain = [("instance_id", "in", instances.ids)]
        category_domain = [("instance_id", "in", instances.ids)]
        coupon_domain = ["|", ("instance_id", "=", False), ("instance_id", "in", instances.ids)]

        if date_from and date_to:
            product_domain += [
                ("synced_on", ">=", date_from),
                ("synced_on", "<=", date_to),
            ]
            order_domain += [
                ("date_created", ">=", date_from),
                ("date_created", "<=", date_to),
            ]
            category_domain += [
                ("synced_on", ">=", date_from),
                ("synced_on", "<=", date_to),
            ]
            coupon_domain += [
                ("synced_on", ">=", date_from),
                ("synced_on", "<=", date_to),
            ]

        orders = Order.search(order_domain)
        return {
            "products": Product.search_count(product_domain),
            "orders": len(orders),
            "customers": self._customer_count(
                instances, date_from=date_from, date_to=date_to
            ),
            "categories": Category.search_count(category_domain),
            "coupons": Coupon.search_count(coupon_domain),
            "total_sales": sum(orders.mapped("total_amount")),
            "net_sales": sum(orders.mapped("total_amount")),
        }

    def _order_status_breakdown(self, instances, date_from, date_to):
        Order = self.env["woo.order.sync"]
        domain = [("instance_id", "in", instances.ids)]
        if date_from and date_to:
            domain += [
                ("date_created", ">=", date_from),
                ("date_created", "<=", date_to),
            ]

        # ``_read_group`` returns a list of tuples: [(status_value, count), ...]
        groups = Order._read_group(
            domain, groupby=["status"], aggregates=["__count"]
        )
        counts = {status: count for status, count in groups if status}
        return {
            "pending": counts.get("pending", 0),
            "processing": counts.get("processing", 0),
            "completed": counts.get("completed", 0),
            "cancelled": counts.get("cancelled", 0),
            "refunded": counts.get("refunded", 0),
            "failed": counts.get("failed", 0),
            "on-hold": counts.get("on-hold", 0),
        }

    def _payment_breakdown(self, instances, date_from, date_to):
        Order = self.env["woo.order.sync"]
        domain = [("instance_id", "in", instances.ids)]
        if date_from and date_to:
            domain += [
                ("date_created", ">=", date_from),
                ("date_created", "<=", date_to),
            ]

        # _read_group with multiple aggregates returns tuples of
        # (groupby_value, count, sum) in declared order.
        groups = Order._read_group(
            domain,
            groupby=["payment_method_title"],
            aggregates=["__count", "total_amount:sum"],
        )
        return [
            {
                "title": title or "Unknown",
                "count": count or 0,
                "amount": float(amount or 0.0),
            }
            for title, count, amount in groups
        ]

    def _recent_orders(self, instances, date_from, date_to, limit=6):
        Order = self.env["woo.order.sync"]
        domain = [("instance_id", "in", instances.ids)]
        if date_from and date_to:
            domain += [
                ("date_created", ">=", date_from),
                ("date_created", "<=", date_to),
            ]
        orders = Order.search(
            domain, order="date_created desc, synced_on desc", limit=limit
        )
        return [
            {
                "name": o.name,
                "customer": o.customer_name or o.customer_email or "Guest",
                "date": o.date_created or o.synced_on,
                "amount": o.total_amount,
                "currency": o.currency,
                "instance": o.instance_id.name,
            }
            for o in orders
        ]

    def _sales_window_summary(self, instances, days, reference_date):
        Order = self.env["woo.order.sync"]
        current_start = reference_date - timedelta(days=days)
        previous_start = current_start - timedelta(days=days)

        current_domain = [
            ("instance_id", "in", instances.ids),
            ("date_created", ">=", current_start.strftime("%Y-%m-%d %H:%M:%S")),
            ("date_created", "<=", reference_date.strftime("%Y-%m-%d %H:%M:%S")),
        ]
        previous_domain = [
            ("instance_id", "in", instances.ids),
            ("date_created", ">=", previous_start.strftime("%Y-%m-%d %H:%M:%S")),
            ("date_created", "<", current_start.strftime("%Y-%m-%d %H:%M:%S")),
        ]

        current_orders = Order.search(current_domain)
        previous_orders = Order.search(previous_domain)
        current_revenue = sum(current_orders.mapped("total_amount"))
        previous_revenue = sum(previous_orders.mapped("total_amount"))
        current_count = len(current_orders)
        previous_count = len(previous_orders)

        revenue_change_pct = (
            ((current_revenue - previous_revenue) / previous_revenue) * 100
            if previous_revenue
            else (100.0 if current_revenue else 0.0)
        )
        order_change_pct = (
            ((current_count - previous_count) / previous_count) * 100
            if previous_count
            else (100.0 if current_count else 0.0)
        )

        return {
            "days": days,
            "revenue": round(current_revenue, 2),
            "orders": current_count,
            "previous_revenue": round(previous_revenue, 2),
            "previous_orders": previous_count,
            "revenue_change_pct": round(revenue_change_pct, 1),
            "order_change_pct": round(order_change_pct, 1),
        }

    def _top_products_summary(self, instances, reference_date):
        Line = self.env["woo.order.line.sync"]
        since = reference_date - timedelta(days=30)
        lines = Line.search(
            [
                ("order_sync_id.instance_id", "in", instances.ids),
                ("order_sync_id.date_created", ">=", since.strftime("%Y-%m-%d %H:%M:%S")),
            ]
        )

        bucket = {}
        for line in lines:
            key = line.sku or line.product_name or str(line.id)
            bucket.setdefault(
                key,
                {
                    "name": line.product_name or line.sku or "Unknown Product",
                    "sku": line.sku,
                    "units_sold_30_days": 0.0,
                    "revenue_30_days": 0.0,
                },
            )
            bucket[key]["units_sold_30_days"] += float(line.quantity or 0.0)
            bucket[key]["revenue_30_days"] += float(line.subtotal or 0.0)

        products = list(bucket.values())
        products.sort(
            key=lambda item: (-item["units_sold_30_days"], -item["revenue_30_days"], item["name"])
        )
        return products[:10]

    def _inventory_risk_summary(self, instances):
        Product = self.env["woo.product.sync"]
        products = Product.search([("instance_id", "in", instances.ids)])
        low_stock = []
        risk_items = []
        slow_moving = []

        top_products = self._top_products_summary(instances, datetime.utcnow())
        sales_by_sku = {item.get("sku"): item for item in top_products if item.get("sku")}

        for product in products:
            current_stock = float(product.qty_available or 0.0)
            velocity = 0.0
            sold_item = sales_by_sku.get(product.sku)
            if sold_item:
                velocity = float(sold_item.get("units_sold_30_days", 0.0)) / 30.0

            if current_stock <= 10:
                low_stock.append(
                    {
                        "name": product.name,
                        "sku": product.sku,
                        "current_stock": current_stock,
                        "stock_status": product.stock_status,
                    }
                )

            if velocity > 0 and current_stock > 0:
                days_to_stockout = round(current_stock / velocity, 1)
                if days_to_stockout <= 14:
                    risk_items.append(
                        {
                            "name": product.name,
                            "sku": product.sku,
                            "current_stock": current_stock,
                            "days_to_stockout": days_to_stockout,
                            "daily_velocity": round(velocity, 2),
                        }
                    )

            units_sold = float(sold_item.get("units_sold_30_days", 0.0)) if sold_item else 0.0
            if current_stock > 0 and units_sold <= 1:
                slow_moving.append(
                    {
                        "name": product.name,
                        "sku": product.sku,
                        "current_stock": current_stock,
                        "units_sold_30_days": units_sold,
                    }
                )

        low_stock.sort(key=lambda item: (item["current_stock"], item["name"]))
        risk_items.sort(key=lambda item: (item["days_to_stockout"], item["name"]))
        slow_moving.sort(key=lambda item: (item["units_sold_30_days"], -item["current_stock"]))

        return {
            "low_stock_products": low_stock[:10],
            "products_at_risk_of_stockout": risk_items[:10],
            "low_sales_products": slow_moving[:10],
            "top_selling_products": top_products,
        }

    def _latest_ai_insight(self, instances, range_days, is_all):
        Insight = self.env["woo.ai.insight"].sudo()
        domain = [("range_days", "=", int(range_days or 30))]
        if is_all:
            domain += [("scope", "=", "all"), ("instance_id", "=", False)]
        else:
            domain += [("scope", "=", "instance"), ("instance_id", "=", instances[:1].id)]
        insight = Insight.search(domain, limit=1)
        if not insight:
            return {
                "summary_text": "",
                "status": "draft",
                "generated_at": False,
                "actionable_recommendations": [],
                "predicted_top_products_to_restock": [],
                "products_at_risk_of_stockout": [],
                "low_sales_products": [],
                "sales_summary": {},
                "repeat_customers": [],
                "error_message": "",
            }
        return insight.get_payload()

    def _build_ai_metrics(self, instances):
        from ..services.woo_ai_service import WooAIService

        reference_date = datetime.utcnow()
        sales_7 = self._sales_window_summary(instances, 7, reference_date)
        sales_30 = self._sales_window_summary(instances, 30, reference_date)
        inventory = self._inventory_risk_summary(instances)
        repeat_customers = WooAIService(self.env).build_repeat_customers(
            self.env["woo.order.sync"].search([("instance_id", "in", instances.ids)])
        )
        low_stock_map = {
            item.get("sku"): item
            for item in inventory["products_at_risk_of_stockout"] + inventory["low_stock_products"]
            if item.get("sku")
        }
        service = WooAIService(self.env)

        return {
            "sales_last_7_days": sales_7,
            "sales_last_30_days": sales_30,
            "top_selling_products": inventory["top_selling_products"],
            "low_stock_products": inventory["low_stock_products"],
            "products_at_risk_of_stockout": inventory["products_at_risk_of_stockout"],
            "low_sales_products": inventory["low_sales_products"],
            "repeat_customers": repeat_customers,
            "predicted_top_products_to_restock": service.build_top_seller_restock_candidates(
                inventory["top_selling_products"], low_stock_map
            ),
        }

    @api.model
    def get_dashboard_data(self, range="30", instance_id=None, fast=False):
        return self.get_analytics_data(range=range, instance_id=instance_id, fast=fast)

    @api.model
    def get_instances(self):
        instances = self._get_active_instances()
        return [{"id": inst.id, "name": inst.name} for inst in instances]

    @api.model
    def get_analytics_data(self, range="30", instance_id=None, fast=False):
        try:
            days = int(range)
        except Exception:
            days = 30
        # Use full local-day boundaries for dashboard ranges so "Last 7 days"
        # always includes today's records the same way "Today" does.
        today = fields.Date.context_today(self)
        if days <= 0:
            date_from = datetime.combine(today, time.min)
            date_to = datetime.combine(today, time.max)
        else:
            # Last N days inclusive: [today-(N-1) 00:00:00, today 23:59:59]
            start_day = today - timedelta(days=max(days - 1, 0))
            date_from = datetime.combine(start_day, time.min)
            date_to = datetime.combine(today, time.max)

        after_api = date_from.strftime("%Y-%m-%dT00:00:00")
        before_api = date_to.strftime("%Y-%m-%dT23:59:59")
        after_local = date_from.strftime("%Y-%m-%d %H:%M:%S")
        before_local = date_to.strftime("%Y-%m-%d %H:%M:%S")

        instances = self._get_active_instances()
        if not instances:
            raise UserError("No active WooCommerce instance found.")

        if instance_id and str(instance_id).lower() == "all":
            selected_instances = instances
            is_all = True
        else:
            instance = self._get_instance_or_raise(instance_id)
            selected_instances = self.env["woo.instance"].browse(instance.id)
            is_all = False

        total_products = 0
        total_orders = 0
        total_customers = 0
        total_categories = 0
        total_coupons = 0
        total_sales = 0.0
        net_sales = 0.0
        intervals_map = {}
        categories = []
        products = []

        if fast:
            local_totals = self._totals_from_local_sync(
                selected_instances,
                date_from=after_local,
                date_to=before_local,
            )

            total_products = local_totals["products"]
            total_orders = local_totals["orders"]
            total_customers = local_totals["customers"]
            total_categories = local_totals["categories"]
            total_coupons = local_totals["coupons"]
            total_sales = local_totals["total_sales"]
            net_sales = local_totals["net_sales"]

            return {
                "totals": {
                    "instances": len(instances),
                    "products": total_products,
                    "orders": total_orders,
                    "customers": total_customers,
                    "categories": total_categories,
                    "coupons": total_coupons,
                    "total_sales": total_sales,
                    "net_sales": net_sales,
                },
                "intervals": [],
                "categories": [],
                "products": [],
                "order_status": {},
                "payments": [],
                "gift_cards": {
                    "total": 0,
                    "used": 0,
                    "pending": 0,
                    "expired": 0,
                    "no_balance": 0,
                },
                "recent_orders": self._recent_orders(
                    selected_instances, after_local, before_local
                ),
                "meta": {
                    "date_from": after_local,
                    "date_to": before_local,
                    "instance_name": "All Instances" if is_all else selected_instances[:1].name,
                    "is_all": is_all,
                },
                "ai_insight": self._latest_ai_insight(selected_instances, days, is_all),
            }

        for inst in selected_instances:
            revenue = self._instance_fetch_json(
                inst,
                "wp-json/wc-analytics/reports/revenue/stats",
                {"after": after_api, "before": before_api, "interval": "day"},
                timeout=6,
            )

            total_products += self._instance_total_from_header(inst, "products")
            total_orders += self._instance_total_from_header(inst, "orders")
            total_customers += self._instance_total_from_header(inst, "customers")
            total_categories += self._instance_total_from_header(inst, "products/categories")

            totals = revenue.get("totals", {}) or {}
            total_sales += float(totals.get("total_sales", 0.0) or 0.0)
            net_sales += float(totals.get("net_sales", 0.0) or 0.0)

            for i in revenue.get("intervals", []) or []:
                key = i.get("interval")
                if not key:
                    continue
                existing = intervals_map.setdefault(key, {
                    "interval": key,
                    "subtotals": {"total_sales": 0.0, "orders_count": 0},
                })
                existing["subtotals"]["total_sales"] += float(
                    i.get("subtotals", {}).get("total_sales", 0.0) or 0.0
                )
                existing["subtotals"]["orders_count"] += int(
                    i.get("subtotals", {}).get("orders_count", 0) or 0
                )

            if not is_all:
                categories = self._instance_fetch_json(
                    inst,
                    "wp-json/wc-analytics/reports/categories",
                    {"after": after_api, "before": before_api, "per_page": 5},
                    timeout=5,
                ) or []

                products = self._instance_fetch_json(
                    inst,
                    "wp-json/wc-analytics/reports/products",
                    {"after": after_api, "before": before_api, "per_page": 5},
                    timeout=5,
                ) or []

        intervals = sorted(intervals_map.values(), key=lambda x: x["interval"])

        if total_customers == 0:
            total_customers = self._customer_count(selected_instances)

        local_totals = self._totals_from_local_sync(
            selected_instances,
            date_from=after_local,
            date_to=before_local,
        )

        # BUG-16: the dashboard previously took ``max()`` of the WooCommerce
        # X-WP-Total header (which reports all-time counts for the resource,
        # not a date-windowed slice) and the locally summed value. When the
        # user picked "Today", local was small (0 or 1) but the WC header
        # was the all-time total — ``max`` returned the all-time number and
        # the user saw 30-day-ish data in a 1-day filter.
        #
        # Source of truth must be the locally synced records inside the
        # selected window, since that's what every other dashboard tile and
        # the Orders list view reflect. WC analytics totals are still used
        # as a cold-start fallback for stores where the local sync table
        # is empty.
        total_products = local_totals["products"] or total_products
        total_orders = local_totals["orders"] or total_orders
        total_customers = local_totals["customers"] or total_customers
        total_categories = local_totals["categories"] or total_categories
        total_coupons = local_totals["coupons"]
        # Revenue: same rationale. WC "total_sales" / "net_sales" headers
        # include refund and rounding adjustments that won't match the raw
        # order sum visible in the Orders list view.
        if local_totals["total_sales"]:
            total_sales = local_totals["total_sales"]
        if local_totals["net_sales"]:
            net_sales = local_totals["net_sales"]

        return {
            "totals": {
                "instances": len(instances),
                "products": total_products,
                "orders": total_orders,
                "customers": total_customers,
                "categories": total_categories,
                "coupons": total_coupons,
                "total_sales": total_sales,
                "net_sales": net_sales,
            },
            "intervals": intervals,
            "categories": categories,
            "products": products,
            "order_status": self._order_status_breakdown(
                selected_instances, after_local, before_local
            ),
            "payments": self._payment_breakdown(
                selected_instances, after_local, before_local
            ),
            "gift_cards": {
                "total": 0,
                "used": 0,
                "pending": 0,
                "expired": 0,
                "no_balance": 0,
            },
            "recent_orders": self._recent_orders(
                selected_instances, after_local, before_local
            ),
            "meta": {
                "date_from": after_local,
                "date_to": before_local,
                "instance_name": "All Instances" if is_all else selected_instances[:1].name,
                "is_all": is_all,
            },
            "ai_insight": self._latest_ai_insight(selected_instances, days, is_all),
        }

    @api.model
    def manual_sync(self, instance_id=None):
        def _sync_instance(instance):
            errors = []
            success = []
            for method_name in ("action_sync_products", "action_sync_categories", "action_sync_orders", "action_sync_coupons"):
                method = getattr(instance, method_name, False)
                if not method:
                    continue
                try:
                    method()
                    success.append(method_name)
                except Exception as exc:
                    errors.append(f"{method_name}: {exc}")
            return {
                "instance": instance.display_name,
                "success": success,
                "errors": errors,
            }

        results = []
        if instance_id and str(instance_id).lower() != "all":
            instance = self._get_instance_or_raise(instance_id)
            results.append(_sync_instance(instance))
        else:
            instances = self._get_active_instances()
            for instance in instances:
                results.append(_sync_instance(instance))

        total_success = sum(len(item["success"]) for item in results)
        total_errors = sum(len(item["errors"]) for item in results)
        all_errors = [err for item in results for err in item["errors"]]

        return {
            "ok": total_errors == 0,
            "total_success": total_success,
            "total_errors": total_errors,
            "errors": all_errors,
            "results": results,
        }

    @api.model
    def generate_ai_insights(self, range="30", instance_id=None):
        """Generate AI insights for the dashboard.

        This method never raises: every failure path returns a JSON-able dict
        with ``status`` set to ``"failed"`` and a human-readable
        ``error_message``. The frontend renders that message in a single
        toast, which avoids the stacked "Odoo Server Error" modals that would
        otherwise appear (one from the framework error_service plus one from
        our own catch block plus a lingering "Generating..." info toast).
        """
        try:
            from ..services.woo_ai_service import WooAIService

            try:
                days = int(range or 30)
            except (TypeError, ValueError):
                days = 30

            instances = self._get_active_instances()
            if not instances:
                return self._ai_insight_error_payload(
                    "No active WooCommerce instance found. "
                    "Configure an instance before generating AI insights."
                )

            if instance_id and str(instance_id).lower() == "all":
                selected_instances = instances
                scope = "all"
                instance = False
                instance_name = "All Instances"
            else:
                try:
                    instance = self._get_instance_or_raise(instance_id)
                except Exception as exc:
                    return self._ai_insight_error_payload(str(exc))
                selected_instances = self.env["woo.instance"].browse(instance.id)
                scope = "instance"
                instance_name = selected_instances[:1].name or "Instance"

            try:
                metrics = self._build_ai_metrics(selected_instances)
            except Exception as exc:
                _logger.exception("Failed to build AI metrics: %s", exc)
                return self._ai_insight_error_payload(
                    "Could not collect dashboard metrics: %s" % exc
                )

            service = WooAIService(self.env)
            result = service.generate_sales_inventory_insights(
                metrics,
                {
                    "instance_name": instance_name,
                    "range_days": days,
                    "instance_count": len(selected_instances),
                },
            )

            try:
                record = self.env["woo.ai.insight"].sudo().upsert_latest(
                    {
                        "name": "AI Insight - %s" % instance_name,
                        "instance_id": instance.id if instance else False,
                        "scope": scope,
                        "range_days": days,
                        "summary_text": result["summary_text"],
                        "insight_json": json.dumps(result["insight_payload"], default=str),
                        "status": result["status"],
                        "generated_at": result["generated_at"],
                        "error_message": result.get("error_message") or False,
                    }
                )
                return record.get_payload()
            except Exception as exc:
                _logger.exception("Failed to persist AI insight record: %s", exc)
                payload = dict(result.get("insight_payload") or {})
                payload.update(
                    {
                        "summary_text": result.get("summary_text") or "",
                        "status": "fallback",
                        "generated_at": result.get("generated_at"),
                        "error_message": "Could not save insight: %s" % exc,
                    }
                )
                return payload
        except Exception as exc:
            _logger.exception("Unexpected error in generate_ai_insights: %s", exc)
            return self._ai_insight_error_payload(
                "Unexpected error while generating AI insights: %s" % exc
            )

    def _ai_insight_error_payload(self, message):
        return {
            "summary_text": "",
            "status": "failed",
            "generated_at": fields.Datetime.now(),
            "error_message": message,
            "actionable_recommendations": [],
            "predicted_top_products_to_restock": [],
            "products_at_risk_of_stockout": [],
            "low_sales_products": [],
            "sales_summary": {},
            "repeat_customers": [],
        }
