from collections import defaultdict
from datetime import datetime, timedelta


class WooSimpleChatbotService:
    """Intent-based chatbot service for WooCommerce connector questions."""

    FALLBACK_REPLY = (
        "I'm here to help with WooCommerce connector information such as orders, "
        "products, inventory, and sync status."
    )

    def __init__(self, env):
        self.env = env

    def detect_intent(self, message):
        text = (message or "").strip().lower()
        if not text:
            return {"intent": "fallback"}

        scored = self._score_intents(text)
        best_intent = max(scored, key=scored.get)
        if scored[best_intent] <= 0:
            return {"intent": "fallback"}
        return {"intent": best_intent}

    def _score_intents(self, text):
        tokens = self._tokenize(text)
        scores = {
            "today_orders": 0,
            "weekly_orders_count": 0,
            "recent_orders": 0,
            "pending_orders": 0,
            "low_stock_products": 0,
            "recent_products": 0,
            "top_selling_products": 0,
            "customers_list": 0,
            "sync_status": 0,
            "help": 0,
            "fallback": 0,
        }

        if self._contains_any(text, ["help", "what can you do", "commands list", "available options"]):
            scores["help"] += 10

        if self._contains_any_token(tokens, ["order", "orders", "sale", "sales"]):
            scores["recent_orders"] += 3
            scores["today_orders"] += 1
            scores["weekly_orders_count"] += 1
            scores["pending_orders"] += 1

        if self._contains_any_token(tokens, ["today", "todays", "current"]):
            scores["today_orders"] += 5

        if self._contains_any(text, ["this week", "weekly", "week"]):
            scores["weekly_orders_count"] += 5
        if self._contains_any_token(tokens, ["count", "total", "number"]) or "how many" in text:
            scores["weekly_orders_count"] += 3

        if self._contains_any_token(tokens, ["recent", "latest", "last", "newest"]):
            scores["recent_orders"] += 4
            scores["recent_products"] += 4

        if self._contains_any(text, ["pending", "waiting for processing", "draft", "unpaid", "not processed", "processing"]):
            scores["pending_orders"] += 6

        if self._contains_any_token(tokens, ["stock", "inventory"]):
            scores["low_stock_products"] += 4
        if self._contains_any(text, ["low stock", "running out of stock", "inventory shortage", "stock alert"]):
            scores["low_stock_products"] += 6

        if self._contains_any_token(tokens, ["product", "products", "item", "items"]):
            scores["recent_products"] += 3
            scores["top_selling_products"] += 2
        if self._contains_any(text, ["recently added", "new products", "latest products", "newest products"]):
            scores["recent_products"] += 5
        if self._contains_any(text, ["top products", "best selling", "most sold", "popular products", "top sales items", "top selling"]):
            scores["top_selling_products"] += 7

        if self._contains_any_token(tokens, ["customer", "customers"]):
            scores["customers_list"] += 6
        if self._contains_any(text, ["show customers", "recent customers", "customer list", "new customers"]):
            scores["customers_list"] += 4

        if self._contains_any_token(tokens, ["sync", "connector", "woocommerce"]):
            scores["sync_status"] += 4
        if self._contains_any(text, ["sync status", "connector status", "is sync working", "last sync result", "woocommerce connection status"]):
            scores["sync_status"] += 6

        return scores

    def _tokenize(self, text):
        sanitized = text
        for char in "?.,!:/-_":
            sanitized = sanitized.replace(char, " ")
        return set(part for part in sanitized.split() if part)

    def _contains_any(self, text, phrases):
        return any(phrase in text for phrase in phrases)

    def _contains_any_token(self, tokens, candidates):
        return any(candidate in tokens for candidate in candidates)

    def get_reply(self, message):
        intent_payload = self.detect_intent(message)
        intent = intent_payload["intent"]
        handlers = {
            "today_orders": self._today_orders_reply,
            "weekly_orders_count": self._weekly_orders_count_reply,
            "recent_orders": self._recent_orders_reply,
            "pending_orders": self._pending_orders_reply,
            "low_stock_products": self._low_stock_reply,
            "recent_products": self._recent_products_reply,
            "top_selling_products": self._top_products_reply,
            "customers_list": self._customer_reply,
            "sync_status": self._sync_status_reply,
            "help": self._help_reply,
            "fallback": lambda: self.FALLBACK_REPLY,
        }
        reply = handlers[intent]()
        return {"intent": intent, "reply": reply}

    def _today_orders_reply(self):
        Order = self.env["woo.order.sync"].sudo()
        today = datetime.utcnow()
        start = today.replace(hour=0, minute=0, second=0, microsecond=0)
        end = start + timedelta(days=1)
        domain = [
            ("date_created", ">=", start.strftime("%Y-%m-%d %H:%M:%S")),
            ("date_created", "<", end.strftime("%Y-%m-%d %H:%M:%S")),
        ]
        orders = Order.search(domain, order="date_created desc", limit=5)
        count = Order.search_count(domain)
        if not count:
            return "No WooCommerce orders were created today."
        refs = ", ".join(order.name or str(order.woo_order_id or order.id) for order in orders)
        return "There are %s WooCommerce orders created today. Recent ones: %s." % (count, refs)

    def _weekly_orders_count_reply(self):
        Order = self.env["woo.order.sync"].sudo()
        now = datetime.utcnow()
        start = (now - timedelta(days=now.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)
        domain = [("date_created", ">=", start.strftime("%Y-%m-%d %H:%M:%S"))]
        count = Order.search_count(domain)
        return "There are %s WooCommerce orders this week." % count

    def _recent_orders_reply(self):
        Order = self.env["woo.order.sync"].sudo()
        orders = Order.search([], order="date_created desc, synced_on desc", limit=5)
        if not orders:
            return "No synced WooCommerce orders were found."
        lines = []
        for order in orders:
            ref = order.name or order.woo_order_id or order.id
            customer = order.customer_name or order.customer_email or "Guest"
            amount = order.total_amount or 0.0
            lines.append("%s for %s (%s)" % (ref, customer, amount))
        return "Recent WooCommerce orders: %s." % "; ".join(lines)

    def _pending_orders_reply(self):
        Order = self.env["woo.order.sync"].sudo()
        domain = [("status", "in", ["pending", "on-hold", "processing"])]
        count = Order.search_count(domain)
        orders = Order.search(domain, order="date_created desc", limit=5)
        if not count:
            return "There are no pending WooCommerce orders right now."
        refs = ", ".join(order.name or str(order.woo_order_id or order.id) for order in orders)
        return "There are %s pending WooCommerce orders. Latest pending orders: %s." % (count, refs)

    def _low_stock_reply(self):
        Product = self.env["woo.product.sync"].sudo()
        domain = [("qty_available", "<=", 5), ("qty_available", ">", 0)]
        products = Product.search(domain, order="qty_available asc, name asc", limit=5)
        count = Product.search_count(domain)
        if not count:
            return "There are no low stock products right now."
        names = ", ".join("%s (%s)" % (product.name, int(product.qty_available or 0)) for product in products)
        return "There are %s low stock products. Most urgent: %s." % (count, names)

    def _recent_products_reply(self):
        Product = self.env["woo.product.sync"].sudo()
        products = Product.search([], order="create_date desc, id desc", limit=5)
        if not products:
            return "No synced WooCommerce products were found."
        names = ", ".join(product.name for product in products)
        return "Recently added WooCommerce products: %s." % names

    def _top_products_reply(self):
        Line = self.env["woo.order.line.sync"].sudo()
        since = (datetime.utcnow() - timedelta(days=30)).strftime("%Y-%m-%d %H:%M:%S")
        lines = Line.search([("order_sync_id.date_created", ">=", since)])
        if not lines:
            return "I could not find recent order lines to calculate top products."

        bucket = defaultdict(float)
        for line in lines:
            name = line.product_name or line.sku or "Unknown Product"
            bucket[name] += float(line.quantity or 0.0)

        top_items = sorted(bucket.items(), key=lambda item: (-item[1], item[0]))[:5]
        summary = ", ".join("%s (%s sold)" % (name, int(qty)) for name, qty in top_items)
        return "Top selling products: %s." % summary

    def _customer_reply(self):
        Customer = self.env["woo.customer.sync"].sudo()
        count = Customer.search_count([])
        latest = Customer.search([], order="write_date desc, id desc", limit=5)
        if not count:
            return "No synced WooCommerce customers were found."
        names = ", ".join(customer.name or customer.email or "Customer" for customer in latest)
        return "There are %s synced customers. Recent customers: %s." % (count, names)

    def _sync_status_reply(self):
        checks = [
            ("orders", "woo.order.sync"),
            ("products", "woo.product.sync"),
            ("customers", "woo.customer.sync"),
            ("categories", "woo.category.sync"),
            ("coupons", "woo.coupon.sync"),
        ]
        parts = []
        for label, model_name in checks:
            model = self.env[model_name].sudo()
            if "state" not in model._fields:
                continue
            failed = model.search_count([("state", "=", "failed")])
            parts.append("%s failed %s" % (failed, label))
        if not parts:
            return "I could not find sync status fields on the connector models."
        return "Current WooCommerce sync status: %s." % ", ".join(parts)

    def _help_reply(self):
        return (
            "You can ask about today's orders, weekly orders count, recent orders, pending orders, "
            "low stock products, recent products, top selling products, customers, or sync status."
        )
