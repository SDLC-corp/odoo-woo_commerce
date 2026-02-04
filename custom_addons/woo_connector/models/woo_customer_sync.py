from odoo import models, fields, api, _
from odoo.exceptions import UserError


class WooCustomerSync(models.Model):
    _name = "woo.customer.sync"
    _description = "WooCommerce Customers"
    _order = "synced_on desc"
    _inherit = "woo.sync.engine"
    _rec_name = "name"

    # --------------------------------------------------
    # CORE FIELDS
    # --------------------------------------------------
    instance_id = fields.Many2one(
        "woo.instance",
        required=True,
        ondelete="cascade",
    )

    name = fields.Char(string="Customer Name", required=True)

    woo_customer_id = fields.Char(
        string="Woo Customer ID",
        required=True,
        index=True,
    )

    email = fields.Char(string="Email")
    phone = fields.Char(string="Phone")

    state = fields.Selection(
        [
            ("draft", "Draft"),
            ("synced", "Synced"),
            ("error", "Error"),
        ],
        default="synced",
        string="Status",
        tracking=True,
    )

    synced_on = fields.Datetime(string="Synced On")

    # --------------------------------------------------
    # SMART BUTTON (ORDERS)
    # --------------------------------------------------
    order_count = fields.Integer(
        compute="_compute_order_count",
        string="Orders",
    )

    # --------------------------------------------------
    # COMPUTE
    # --------------------------------------------------
    @api.depends("email")
    def _compute_order_count(self):
        WooOrder = self.env["woo.order.sync"]
        for rec in self:
            if rec.email:
                rec.order_count = WooOrder.search_count(
                    [
                        ("customer_email", "=", rec.email),
                        ("instance_id", "=", rec.instance_id.id),
                    ]
                )
            else:
                rec.order_count = 0

    # --------------------------------------------------
    # HEADER BUTTON ACTION
    # --------------------------------------------------
    def action_push_to_woo(self):
        """Create / Update customer in WooCommerce"""
        self.ensure_one()

        wcapi = self.instance_id._get_wcapi(self.instance_id)

        first_name = (self.name or "").split(" ")[0] if self.name else ""
        last_name = " ".join((self.name or "").split(" ")[1:]) if self.name else ""

        payload = {
            "email": self.email,
            "first_name": first_name,
            "last_name": last_name,
            "billing": {
                "email": self.email,
                "phone": self.phone,
            },
        }

        # -----------------------------
        # UPDATE CUSTOMER
        # -----------------------------
        if self.woo_customer_id.isdigit():
            response = wcapi.put(
                f"customers/{self.woo_customer_id}",
                payload
            )

            if response.status_code == 403 and "woocommerce_rest_cannot_edit" in response.text:
                safe_payload = {
                    "first_name": first_name,
                    "last_name": last_name,
                    "billing": {
                        "phone": self.phone,
                    },
                }
                response = wcapi.put(
                    f"customers/{self.woo_customer_id}",
                    safe_payload
                )

        # -----------------------------
        # CREATE CUSTOMER (guest → real)
        # -----------------------------
        else:
            response = wcapi.post(
                "customers",
                payload
            )

        if response.status_code not in (200, 201):
            raise UserError(response.text)

        data = response.json()

        self.write({
            "woo_customer_id": str(data.get("id")),
            "state": "synced",
            "synced_on": fields.Datetime.now(),
        })

        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("WooCommerce"),
                "message": _("Customer synced successfully."),
                "type": "success",
            },
        }

    # --------------------------------------------------
    # SMART BUTTON ACTION
    # --------------------------------------------------
    def action_view_orders(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": _("Woo Orders"),
            "res_model": "woo.order.sync",
            "view_mode": "tree,form",
            "domain": [
                ("customer_email", "=", self.email),
                ("instance_id", "=", self.instance_id.id),
            ],
        }
