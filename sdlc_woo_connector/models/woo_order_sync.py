from odoo import models, fields, api, _
from odoo.exceptions import UserError
from datetime import datetime
import logging

_logger = logging.getLogger(__name__)


class WooOrderSync(models.Model):
    _name = "woo.order.sync"
    _description = "WooCommerce Order"
    _rec_name = "name"
    _order = "synced_on desc"
    _sql_constraints = [
        (
            "woo_order_instance_uniq",
            "unique(instance_id, woo_order_id)",
            "Duplicate Woo order for the same instance is not allowed.",
        ),
    ]

    def init(self):
        super().init()
        self._cleanup_duplicates()

    def _cleanup_duplicates(self, instance_id=None):
        params = []
        where_instance = ""
        if instance_id:
            where_instance = "AND a.instance_id = %s"
            params.append(instance_id)

        self._cr.execute(
            f"""
            DELETE FROM woo_order_sync a
            USING woo_order_sync b
            WHERE a.id < b.id
              AND a.instance_id = b.instance_id
              AND a.woo_order_id = b.woo_order_id
              AND a.woo_order_id IS NOT NULL
              {where_instance}
            """,
            params,
        )

    @api.model_create_multi
    def create(self, vals_list):
        records = self.env["woo.order.sync"]
        for vals in vals_list:
            woo_id = vals.get("woo_order_id")
            instance_id = vals.get("instance_id")
            if woo_id and instance_id:
                existing = self.search(
                    [
                        ("woo_order_id", "=", str(woo_id)),
                        ("instance_id", "=", instance_id),
                    ],
                    limit=1,
                )
                if existing:
                    existing.write(vals)
                    records |= existing
                    continue
            records |= super(WooOrderSync, self).create([vals])
        return records

    # --------------------------------------------------
    # STATE
    # --------------------------------------------------
    state = fields.Selection(
        [
            ("draft", "Draft"),
            ("synced", "Synced"),
            ("failed", "Failed"),
        ],
        default="draft",
        tracking=True,
    )

    # --------------------------------------------------
    # CORE FIELDS
    # --------------------------------------------------
    instance_id = fields.Many2one(
        "woo.instance",
        string="Woo Instance",
        required=True,
        ondelete="cascade",
    )

    woo_order_id = fields.Char(
        string="Woo Order ID",
        required=True,
        index=True,
    )

    name = fields.Char(string="Order Number", required=True)
    customer_name = fields.Char()
    customer_email = fields.Char()

    total_amount = fields.Float()
    currency = fields.Char()
    status = fields.Char()
    payment_method = fields.Char()
    payment_method_title = fields.Char()
    date_created = fields.Datetime()
    customer_note = fields.Text()

    synced_on = fields.Datetime(default=fields.Datetime.now)

    # --------------------------------------------------
    # RELATIONS
    # --------------------------------------------------
    line_ids = fields.One2many(
        "woo.order.line.sync",
        "order_sync_id",
        string="Order Lines",
    )

    sale_order_id = fields.Many2one(
        "sale.order",
        string="Sale Order",
        readonly=True,
    )

    order_state = fields.Selection(
        [
            ("draft", "Draft"),
            ("pending", "Pending Payment"),
            ("confirmed", "Confirmed"),
            ("shipped", "Shipped"),
            ("delivered", "Delivered"),
            ("cancelled", "Cancelled"),
            ("refunded", "Refunded"),
        ],
        string="Order Tracking Status",
        # default="draft",
        tracking=True,
    )
    # woo_status = fields.Char(
    #     string="Woo Order Status",
    #     tracking=True,
    # )
    woo_status = fields.Selection(
        [
            ("pending", "Pending Payment"),
            ("processing", "Processing"),
            ("on-hold", "On Hold"),
            ("completed", "Completed"),
            ("cancelled", "Cancelled"),
            ("refunded", "Refunded"),
            ("failed", "Failed"),
        ],
        string="Woo Order Status",
        tracking=True,
        # default="pending",
    )

    woo_status_label = fields.Char(
        string="Status",
        compute="_compute_woo_status_label",
        store=True,
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

    # --------------------------------------------------
    # ENGINE HOOKS
    # --------------------------------------------------
    def _woo_endpoint(self):
        return "orders"

    def _woo_unique_field(self):
        return "woo_order_id"

    # --------------------------------------------------
    # PAYLOAD MAPPING
    # --------------------------------------------------
    def _prepare_vals(self, o):
        billing = o.get("billing") or {}

        return {
            "woo_order_id": str(o.get("id")),
            "name": o.get("number"),
            "customer_name": f"{billing.get('first_name','')} {billing.get('last_name','')}".strip(),
            "customer_email": billing.get("email"),
            "total_amount": float(o.get("total") or 0.0),
            "currency": o.get("currency"),
            "status": o.get("status"),
            "state": "synced",
            "woo_status": o.get("status"),
            "payment_method": o.get("payment_method"),
            "payment_method_title": o.get("payment_method_title"),
            "date_created": self._parse_woo_datetime(
                o.get("date_created")
            ),
            "customer_note": o.get("customer_note"),
            "synced_on": fields.Datetime.now(),
        }

    # --------------------------------------------------
    # ORDER LINE SYNC
    # --------------------------------------------------
    def sync_order_lines(self, order, payload):
        Product = self.env["product.product"]
        Line = self.env["woo.order.line.sync"]

        order.line_ids.unlink()

        for line in payload.get("line_items", []):
            sku = line.get("sku")

            product = Product.search(
                [("default_code", "=", sku)],
                limit=1
            )

            Line.create({
                "order_sync_id": order.id,
                "woo_line_id": str(line.get("id")),
                "product_name": line.get("name"),
                "sku": sku,
                "quantity": float(line.get("quantity") or 0),
                "price_unit": float(line.get("price") or 0.0),
                "subtotal": float(line.get("subtotal") or 0.0),
                "product_id": product.id if product else False,
            })

    # --------------------------------------------------
    # FULL SYNC FROM WOO
    # --------------------------------------------------
    # def sync_from_woocommerce(self):
    #     self.ensure_one()
    #
    #     instance = self.instance_id
    #     if not instance:
    #         raise UserError(_("WooCommerce instance not configured."))
    #
    #     payload = instance.fetch_order(self.woo_order_id)
    #     if not payload:
    #         raise UserError(_("Order not found in WooCommerce."))
    #
    #     vals = self._prepare_vals(payload)
    #     self.write(vals)
    #     print("vals: ", vals)
    #
    #     self.sync_order_lines(self, payload)

    # --------------------------------------------------
    # CREATE SALE ORDER
    # --------------------------------------------------
    def action_create_sale_order(self):
        self.ensure_one()

        if self.sale_order_id:
            raise UserError(_("Sale Order already exists."))

        if not self.line_ids:
            raise UserError(_("No order lines found."))

        partner = self.env["res.partner"].search(
            [("email", "=", self.customer_email)],
            limit=1,
        )

        if not partner:
            partner = self.env["res.partner"].create({
                "name": self.customer_name or "Woo Customer",
                "email": self.customer_email,
            })

        sale_order = self.env["sale.order"].create({
            "partner_id": partner.id,
            "origin": f"Woo Order {self.name}",
        })

        for line in self.line_ids:
            if not line.product_id:
                raise UserError(
                    _("Missing product mapping for SKU: %s") % (line.sku,)
                )

            self.env["sale.order.line"].create({
                "order_id": sale_order.id,
                "product_id": line.product_id.id,
                "product_uom_qty": line.quantity,
                "price_unit": line.price_unit,
                "name": line.product_name,
            })

        self.sale_order_id = sale_order.id

        return {
            "type": "ir.actions.act_window",
            "res_model": "sale.order",
            "res_id": sale_order.id,
            "view_mode": "form",
        }

    # --------------------------------------------------
    # UI ACTIONS
    # --------------------------------------------------
    def action_add_order(self):
        return {
            "type": "ir.actions.act_window",
            "res_model": "woo.order.sync",
            "view_mode": "form",
            "target": "current",
        }

    def action_update_order(self):
        for record in self:
            record.sync_from_woocommerce()

    def action_push_to_woo(self):
        self.ensure_one()

        if not self.instance_id:
            raise UserError(_("Woo instance missing"))

        if not self.woo_order_id:
            raise UserError(_("Woo Order ID missing"))

        status_value = self.woo_status or self.status
        if not status_value:
            raise UserError(_("Woo status is required to update the order"))

        first_name = (self.customer_name or "").split(" ")[0] if self.customer_name else ""
        last_name = " ".join((self.customer_name or "").split(" ")[1:]) if self.customer_name else ""

        payload = {
            "status": status_value,
            "billing": {
                "email": self.customer_email,
                "first_name": first_name,
                "last_name": last_name,
            },
            "customer_note": self.customer_note or "",
        }

        wcapi = self.instance_id._get_wcapi(self.instance_id)
        response = wcapi.put(
            f"orders/{self.woo_order_id}",
            payload
        )

        if response.status_code != 200:
            raise UserError(response.text)

        data = response.json()
        vals = self._prepare_vals(data)
        vals["order_state"] = self._map_woo_status(data.get("status"))
        self.write(vals)
        self.sync_order_lines(self, data)

        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("WooCommerce"),
                "message": _("Order pushed to WooCommerce."),
                "type": "success",
            },
        }

    def action_pull_from_woo(self):
        self.ensure_one()
        self.sync_from_woocommerce()

        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("WooCommerce"),
                "message": _("Order pulled from WooCommerce."),
                "type": "success",
            },
        }

    def action_cleanup_duplicates(self):
        domain = []
        if self:
            domain = [("id", "in", self.ids)]

        Order = self.env["woo.order.sync"]
        records = Order.search(domain)
        seen = {}
        to_delete = self.env["woo.order.sync"]

        for rec in records.sorted(key=lambda r: (r.woo_order_id or "", r.instance_id.id, r.synced_on or r.create_date or fields.Datetime.now()), reverse=True):
            key = (rec.instance_id.id, rec.woo_order_id)
            if not rec.woo_order_id or not rec.instance_id:
                continue
            if key in seen:
                to_delete |= rec
            else:
                seen[key] = rec.id

        if to_delete:
            to_delete.unlink()

        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("WooCommerce"),
                "message": _("Duplicate orders cleaned: %s") % len(to_delete),
                "type": "success",
            },
        }


    def _map_woo_status(self, woo_status):
        # print("woo_status", woo_status)
        return {
            "pending": "pending",
            "processing": "confirmed",
            "on-hold": "confirmed",
            "completed": "delivered",
            "cancelled": "cancelled",
            "refunded": "refunded",
            "failed": "cancelled",
        }.get(woo_status, "draft")

    def _compute_woo_status_label(self):
        for rec in self:
            if rec.woo_status:
                rec.woo_status_label = rec.woo_status.replace("-", " ").title()
            else:
                rec.woo_status_label = "Unknown"

    def sync_from_woocommerce(self):
        self.ensure_one()

        instance = self.instance_id
        if not instance:
            raise UserError(_("Woo instance missing"))

        payload = instance.fetch_order(self.woo_order_id)
        # print("payload", payload)
        if not payload:
            raise UserError(_("Order not found in WooCommerce"))

        # Prepare full update values
        vals = self._prepare_vals(payload)

        # Map Woo status to internal order state
        vals["order_state"] = self._map_woo_status(payload.get("status"))

        # Update record
        self.write(vals)

        # Sync order lines
        self.sync_order_lines(self, payload)

    def cron_sync_woo_order_status(self):
        """
        Automatically sync Woo order statuses
        """
        orders = self.search([
            ("woo_order_id", "!=", False),
            ("instance_id", "!=", False),
        ])

        for order in orders:
            try:
                order.sync_from_woocommerce()
            except Exception as e:
                _logger.warning(
                    "Failed to sync Woo order %s: %s",
                    order.woo_order_id,
                    e,
                )

