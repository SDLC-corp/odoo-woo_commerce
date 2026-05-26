import re

from odoo import models, fields, api, _
from odoo.exceptions import UserError

EMAIL_RE = re.compile(r"^[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}$")


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
        help="WooCommerce Instance this customer belongs to.",
    )

    name = fields.Char(
        string="Customer Name",
        required=True,
        help="Full customer display name shown in both Odoo and WooCommerce.",
    )

    woo_customer_id = fields.Char(
        string="Woo Customer ID",
        index=True,
        help="The numeric ID of this customer in WooCommerce. Empty for guest checkouts.",
    )

    email = fields.Char(
        string="Email",
        help="Customer email used for WooCommerce sync. Always stored and sent in lowercase.",
    )
    phone = fields.Char(
        string="Phone",
        help="Billing phone number sent to WooCommerce.",
    )

    state = fields.Selection(
        [
            ("draft", "Draft"),
            ("synced", "Synced"),
            ("error", "Error"),
        ],
        default="synced",
        string="Status",
        tracking=True,
        help="Sync status with WooCommerce: Draft (not yet sent), Synced (in sync), or Error (last push failed).",
    )

    synced_on = fields.Datetime(
        string="Synced On",
        help="Last date/time this customer was successfully pushed to or pulled from WooCommerce.",
    )

    def _normalized_email(self):
        self.ensure_one()
        return (self.email or "").strip().lower()

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get("email"):
                vals["email"] = vals["email"].strip().lower()
        return super().create(vals_list)

    def write(self, vals):
        if vals.get("email"):
            vals["email"] = vals["email"].strip().lower()
        return super().write(vals)

    # --------------------------------------------------
    # SMART BUTTON (ORDERS)
    # --------------------------------------------------
    order_count = fields.Integer(
        compute="_compute_order_count",
        string="Orders",
        help="Number of WooCommerce orders linked to this customer's email.",
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
        email = self._normalized_email()
        if not email:
            raise UserError(_("Customer email is required for WooCommerce sync."))
        if not EMAIL_RE.match(email):
            raise UserError(_("Invalid email address format: %s") % email)
        if self.email and self.email != email:
            self.with_context(skip_email_normalize=True).write({"email": email})

        first_name = (self.name or "").split(" ")[0] if self.name else ""
        last_name = " ".join((self.name or "").split(" ")[1:]) if self.name else ""

        payload = {
            "email": email,
            "first_name": first_name,
            "last_name": last_name,
            "billing": {
                "email": email,
                "phone": self.phone,
            },
        }

        # -----------------------------
        # UPDATE CUSTOMER
        # -----------------------------
        if (self.woo_customer_id or "").isdigit():
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
            "email": email,
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

    def action_pull_from_woo(self):
        self.ensure_one()

        if not self.instance_id:
            raise UserError(_("Woo instance missing."))

        self.instance_id.action_sync_orders()

        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("WooCommerce"),
                "message": _("Customers refreshed from Woo orders."),
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
            "view_mode": "list,form",
            "domain": [
                ("customer_email", "=", self.email),
                ("instance_id", "=", self.instance_id.id),
            ],
        }
