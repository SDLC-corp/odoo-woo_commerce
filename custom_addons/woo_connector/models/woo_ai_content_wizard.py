from odoo import _, fields, models
from odoo.exceptions import UserError

from ..services.woo_ai_service import WooAIService


class WooAIContentWizard(models.TransientModel):
    _name = "woo.ai.content.wizard"
    _description = "WooCommerce AI Product Content Wizard"

    product_sync_id = fields.Many2one(
        "woo.product.sync",
        string="Woo Product",
        required=True,
        ondelete="cascade",
    )
    generation_type = fields.Selection(
        [
            ("description", "Generate Description"),
            ("short_description", "Generate Short Description"),
            ("seo", "Improve SEO Text"),
            ("tags", "Suggest Tags"),
        ],
        required=True,
        default="description",
    )
    tone = fields.Selection(
        [
            ("professional", "Professional"),
            ("persuasive", "Persuasive"),
            ("concise", "Concise"),
        ],
        default="professional",
        required=True,
    )
    seo_mode = fields.Boolean(string="SEO Mode", default=True)
    status = fields.Selection(
        [("draft", "Draft"), ("success", "Success"), ("fallback", "Fallback"), ("failed", "Failed")],
        default="draft",
        readonly=True,
    )
    generated_at = fields.Datetime(readonly=True)
    error_message = fields.Text(readonly=True)
    generated_long_description = fields.Html(string="Generated Description", sanitize=False)
    generated_short_description = fields.Text(string="Generated Short Description")
    generated_seo_title = fields.Char(string="Generated SEO Title")
    generated_seo_description = fields.Text(string="Generated SEO Description")
    generated_tags_text = fields.Text(string="Generated Tags")

    def _build_product_payload(self):
        self.ensure_one()
        product = self.product_sync_id
        if not product:
            raise UserError(_("Woo product is required for AI content generation."))

        category_names = product.category_ids.mapped("name")
        tag_names = product.tag_ids.mapped("name")
        attributes = []
        if product.product_tmpl_id:
            for line in product.product_tmpl_id.attribute_line_ids:
                values = ", ".join(line.value_ids.mapped("name"))
                attributes.append("%s: %s" % (line.attribute_id.name, values))

        return {
            "name": product.name,
            "sku": product.sku,
            "category_name": ", ".join(category_names),
            "categories": category_names,
            "existing_tags": tag_names,
            "price_label": "%.2f" % float(product.list_price or 0.0),
            "sale_price": product.sale_price,
            "attributes": attributes,
            "current_short_description": product.short_description or "",
            "current_long_description": product.description or "",
            "current_seo_title": product.seo_title or "",
            "current_seo_description": product.seo_description or "",
        }

    def action_generate_preview(self):
        for wizard in self:
            service = WooAIService(wizard.env)
            result = service.generate_product_content(
                wizard._build_product_payload(),
                {
                    "generation_type": wizard.generation_type,
                    "tone": wizard.tone,
                    "seo_mode": wizard.seo_mode,
                },
            )
            wizard.write(
                {
                    "status": result["status"],
                    "generated_at": result["generated_at"],
                    "error_message": result.get("error_message"),
                    "generated_long_description": result["generated_long_description"],
                    "generated_short_description": result["generated_short_description"],
                    "generated_seo_title": result["generated_seo_title"],
                    "generated_seo_description": result["generated_seo_description"],
                    "generated_tags_text": result["generated_tags_text"],
                }
            )
        return {
            "type": "ir.actions.act_window",
            "res_model": "woo.ai.content.wizard",
            "view_mode": "form",
            "res_id": self.id,
            "target": "new",
        }

    def action_apply_to_product(self):
        self.ensure_one()
        product = self.product_sync_id
        service = WooAIService(self.env)

        values = {
            "ai_content_last_generated": self.generated_at or fields.Datetime.now(),
        }
        if self.generation_type == "description":
            values["description"] = self.generated_long_description
        elif self.generation_type == "short_description":
            values["short_description"] = self.generated_short_description
        elif self.generation_type == "seo":
            values.update(
                {
                    "seo_title": self.generated_seo_title,
                    "seo_description": self.generated_seo_description,
                }
            )
        elif self.generation_type == "tags":
            tags = service.summarize_tags(self.generated_tags_text)
            tag_records = self.env["product.tag"]
            for tag_name in tags:
                tag = self.env["product.tag"].search([("name", "=", tag_name)], limit=1)
                if not tag:
                    tag = self.env["product.tag"].create({"name": tag_name})
                tag_records |= tag
            values["tag_ids"] = [(6, 0, tag_records.ids)]

        product.write(values)

        if product.product_tmpl_id:
            tmpl_values = {}
            if values.get("description"):
                tmpl_values["description"] = self.generated_seo_description or self.generated_long_description or ""
            if values.get("short_description"):
                tmpl_values["description_sale"] = self.generated_short_description or ""
            if values.get("seo_title"):
                tmpl_values["description"] = self.generated_seo_description or tmpl_values.get("description") or ""
            if tmpl_values:
                product.product_tmpl_id.write(tmpl_values)

        return {"type": "ir.actions.act_window_close"}
