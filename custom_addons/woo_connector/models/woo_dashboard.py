from odoo import models, api, fields
from odoo.exceptions import UserError
import requests
from datetime import datetime, timedelta
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
            r = requests.get(url, auth=auth, params=params or {}, timeout=30)
            r.raise_for_status()
            return r.json()
        except Exception:
            return {}

    def _total_from_header(self, base, auth_candidates, endpoint):
        for auth in auth_candidates:
            if not auth or not all(auth):
                continue
            try:
                r = requests.get(
                    f"{base}/wp-json/wc/v3/{endpoint}",
                    auth=auth,
                    params={"per_page": 1},
                    timeout=30,
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

    def _customer_count_from_orders(self, instances):
        if not instances:
            return 0
        Order = self.env["woo.order.sync"]
        domain = [("instance_id", "in", instances.ids)]
        groups = Order.read_group(domain, ["customer_email"], ["customer_email"])
        return sum(1 for g in groups if g.get("customer_email"))

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

    def _totals_from_local_sync(self, instances):
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

        domain = [("instance_id", "in", instances.ids)]
        coupon_domain = ["|", ("instance_id", "=", False), ("instance_id", "in", instances.ids)]
        return {
            "products": Product.search_count(domain),
            "orders": Order.search_count(domain),
            "customers": self._customer_count_from_orders(instances),
            "categories": Category.search_count(domain),
            "coupons": Coupon.search_count(coupon_domain),
            "total_sales": sum(Order.search(domain).mapped("total_amount")),
            "net_sales": sum(Order.search(domain).mapped("total_amount")),
        }

    def _order_status_breakdown(self, instances, date_from, date_to):
        Order = self.env["woo.order.sync"]
        domain = [("instance_id", "in", instances.ids)]
        if date_from and date_to:
            domain += [
                ("date_created", ">=", date_from),
                ("date_created", "<=", date_to),
            ]

        groups = Order.read_group(domain, ["status"], ["status"])
        counts = {g["status"]: g["status_count"] for g in groups if g.get("status")}
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

        groups = Order.read_group(
            domain,
            ["payment_method_title", "total_amount:sum"],
            ["payment_method_title"],
        )
        return [
            {
                "title": g.get("payment_method_title") or "Unknown",
                "count": g.get("payment_method_title_count", 0),
                "amount": g.get("total_amount", 0.0),
            }
            for g in groups
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
        days = int(range)
        date_to = datetime.utcnow()
        if days <= 0:
            date_from = date_to.replace(
                hour=0,
                minute=0,
                second=0,
                microsecond=0,
            )
            date_to = date_from.replace(
                hour=23,
                minute=59,
                second=59,
            )
        else:
            date_from = date_to - timedelta(days=days)

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
            snapshot = self._totals_from_snapshots(selected_instances)
            local_totals = self._totals_from_local_sync(selected_instances)

            total_products = snapshot["products"] or local_totals["products"]
            total_orders = snapshot["orders"] or local_totals["orders"]
            total_customers = snapshot["customers"] or local_totals["customers"]
            total_categories = snapshot["categories"] or local_totals["categories"]
            total_coupons = snapshot["coupons"] or local_totals["coupons"]
            total_sales = snapshot["total_sales"] or local_totals["total_sales"]
            net_sales = snapshot["net_sales"] or local_totals["net_sales"]

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
            base = inst.shop_url.rstrip("/")
            auth_v3 = (inst.consumer_key, inst.consumer_secret)
            auth_app = (inst.wp_username, inst.application_password)
            auth_analytics = auth_app if all(auth_app) else auth_v3

            revenue = self._fetch_json(
                f"{base}/wp-json/wc-analytics/reports/revenue/stats",
                auth_analytics,
                {"after": after_api, "before": before_api, "interval": "day"},
            )

            auth_candidates = [auth_v3, auth_app]
            total_products += self._total_from_header(
                base, auth_candidates, "products"
            )
            total_orders += self._total_from_header(
                base, auth_candidates, "orders"
            )
            total_customers += self._total_from_header(
                base, auth_candidates, "customers"
            )
            total_categories += self._total_from_header(
                base, auth_candidates, "products/categories"
            )

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
                categories = self._fetch_json(
                    f"{base}/wp-json/wc-analytics/reports/categories",
                    auth_analytics,
                    {"after": after_api, "before": before_api, "per_page": 5},
                ) or []

                products = self._fetch_json(
                    f"{base}/wp-json/wc-analytics/reports/products",
                    auth_analytics,
                    {"after": after_api, "before": before_api, "per_page": 5},
                ) or []

        intervals = sorted(intervals_map.values(), key=lambda x: x["interval"])

        if total_customers == 0:
            total_customers = self._customer_count_from_orders(selected_instances)

        local_totals = self._totals_from_local_sync(selected_instances)

        # Keep dashboard responsive for live webhook updates by preferring local synced data
        # whenever remote analytics APIs are delayed.
        total_products = max(total_products, local_totals["products"])
        total_orders = max(total_orders, local_totals["orders"])
        total_customers = max(total_customers, local_totals["customers"])
        total_categories = max(total_categories, local_totals["categories"])
        total_coupons = local_totals["coupons"]
        total_sales = max(total_sales, local_totals["total_sales"])
        net_sales = max(net_sales, local_totals["net_sales"])

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
        if instance_id and str(instance_id).lower() != "all":
            instance = self._get_instance_or_raise(instance_id)
            instance.auto_sync_all(force=True)
            return True

        instances = self._get_active_instances()
        for instance in instances:
            instance.auto_sync_all(force=True)
        return True

    @api.model
    def generate_ai_insights(self, range="30", instance_id=None):
        from ..services.woo_ai_service import WooAIService

        days = int(range or 30)
        instances = self._get_active_instances()
        if not instances:
            raise UserError("No active WooCommerce instance found.")

        if instance_id and str(instance_id).lower() == "all":
            selected_instances = instances
            scope = "all"
            instance = False
            instance_name = "All Instances"
        else:
            instance = self._get_instance_or_raise(instance_id)
            selected_instances = self.env["woo.instance"].browse(instance.id)
            scope = "instance"
            instance_name = selected_instances[:1].name

        metrics = self._build_ai_metrics(selected_instances)
        service = WooAIService(self.env)
        result = service.generate_sales_inventory_insights(
            metrics,
            {
                "instance_name": instance_name,
                "range_days": days,
                "instance_count": len(selected_instances),
            },
        )

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
