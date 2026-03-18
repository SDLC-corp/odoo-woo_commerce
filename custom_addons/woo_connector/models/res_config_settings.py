from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = "res.config.settings"

    woocommerce_ai_enabled = fields.Boolean(
        string="Enable WooCommerce AI",
        config_parameter="woocommerce_ai.enabled",
    )
    woocommerce_ai_provider = fields.Char(
        string="AI Provider",
        config_parameter="woocommerce_ai.provider",
    )
    woocommerce_ai_api_key = fields.Char(
        string="AI API Key",
        config_parameter="woocommerce_ai.api_key",
    )
    woocommerce_ai_model = fields.Char(
        string="AI Model",
        config_parameter="woocommerce_ai.model",
    )
    woocommerce_ai_max_tokens = fields.Integer(
        string="AI Max Tokens",
        config_parameter="woocommerce_ai.max_tokens",
    )
    woocommerce_ai_endpoint = fields.Char(
        string="AI Endpoint",
        config_parameter="woocommerce_ai.endpoint",
    )
