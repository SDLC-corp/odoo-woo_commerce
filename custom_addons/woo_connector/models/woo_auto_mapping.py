from odoo import _, fields, models
from odoo.exceptions import UserError


class WooAutoMapping(models.Model):
    _name = "woo.auto.mapping"
    _description = "Woo Auto Mapping"
    _order = "write_date desc, id desc"
    _rec_name = "woo_label"
    _woo_auto_mapping_uniq = models.Constraint(
        "unique(instance_id, mapping_type, woo_key)",
        "Woo mapping already exists for this instance/type/key.",
    )

    instance_id = fields.Many2one(
        "woo.instance",
        string="Woo Instance",
        required=True,
        ondelete="cascade",
        index=True,
        help="WooCommerce Instance this auto mapping applies to.",
    )
    mapping_type = fields.Selection(
        [
            ("payment_method", "Payment Method"),
            ("shipping_method", "Shipping Method"),
            ("tax", "Tax"),
            ("category", "Product Category"),
            ("tag", "Product Tag"),
            ("order_status", "Order Status"),
        ],
        required=True,
        index=True,
        help="Kind of value being mapped from WooCommerce to Odoo (e.g. payment method, shipping method, tax).",
    )
    woo_key = fields.Char(
        required=True,
        index=True,
        help="Raw value or slug used by WooCommerce (e.g. 'bacs', 'flat_rate', 'standard_tax').",
    )
    woo_label = fields.Char(
        required=True,
        help="Human-friendly label shown by WooCommerce for this key.",
    )

    odoo_model = fields.Char(
        help="Odoo model name of the target record (e.g. 'account.journal', 'delivery.carrier').",
    )
    odoo_res_id = fields.Integer(
        help="ID of the target Odoo record this WooCommerce value maps to.",
    )
    odoo_value = fields.Char(
        string="Mapped Value",
        help="Free-text Odoo value used when no specific target record is set.",
    )
    odoo_display_name = fields.Char(
        compute="_compute_odoo_display_name",
        store=False,
        help="Display name of the resolved Odoo target record.",
    )

    auto_created = fields.Boolean(
        default=False,
        index=True,
        help="True when this mapping was created automatically by an import flow.",
    )
    active = fields.Boolean(
        default=True,
        index=True,
        help="Disable to stop this mapping from being applied during sync.",
    )
    note = fields.Text(
        help="Free-form note for ops or QA reference.",
    )

    def _compute_odoo_display_name(self):
        for rec in self:
            display = rec.odoo_value or ""
            if rec.odoo_model and rec.odoo_res_id:
                try:
                    obj = self.env[rec.odoo_model].browse(rec.odoo_res_id)
                    if obj.exists():
                        display = obj.display_name
                except Exception:
                    pass
            rec.odoo_display_name = display

    def action_test_mapping(self):
        """Validate the auto mapping without running a full sync."""
        self.ensure_one()

        issues = []
        if not self.instance_id:
            issues.append(_("Woo Instance is missing."))
        if not self.mapping_type:
            issues.append(_("Mapping Type is required."))
        if not self.woo_key:
            issues.append(_("Woo Key is required."))
        if not self.woo_label:
            issues.append(_("Woo Label is required."))

        target_label = self.odoo_value or ""
        if self.odoo_model and self.odoo_res_id:
            try:
                obj = self.env[self.odoo_model].browse(self.odoo_res_id)
                if not obj.exists():
                    issues.append(
                        _("Target record [%(model)s, id=%(id)s] does not exist.") % {
                            "model": self.odoo_model,
                            "id": self.odoo_res_id,
                        }
                    )
                else:
                    target_label = obj.display_name
            except Exception as exc:
                issues.append(
                    _("Could not resolve target model %(model)s: %(err)s") % {
                        "model": self.odoo_model,
                        "err": exc,
                    }
                )
        elif self.odoo_model and not self.odoo_res_id and not self.odoo_value:
            issues.append(_("Either select a target record or provide a Mapped Value."))

        duplicate = self.search_count(
            [
                ("id", "!=", self.id),
                ("instance_id", "=", self.instance_id.id),
                ("mapping_type", "=", self.mapping_type),
                ("woo_key", "=", self.woo_key),
            ]
        )
        if duplicate:
            issues.append(
                _("A mapping already exists for this instance/type/key combination.")
            )

        if issues:
            raise UserError("\n".join(issues))

        message = _(
            "Mapping looks valid:\n"
            "• Instance: %(instance)s\n"
            "• Type: %(type)s\n"
            "• Woo: %(woo_label)s (%(woo_key)s)\n"
            "• Mapped to: %(target)s"
        ) % {
            "instance": self.instance_id.display_name,
            "type": dict(self._fields["mapping_type"].selection).get(
                self.mapping_type, self.mapping_type
            ),
            "woo_label": self.woo_label,
            "woo_key": self.woo_key,
            "target": target_label or _("(empty)"),
        }
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("Test Mapping"),
                "message": message,
                "type": "success",
                "sticky": False,
            },
        }
