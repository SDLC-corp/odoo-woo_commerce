from odoo import http
from odoo.http import request

from ..services.chatbot_service import WooSimpleChatbotService


class WooSimpleChatbotController(http.Controller):
    @http.route("/ai/chatbot/message", type="json", auth="user", methods=["POST"], csrf=False)
    def ai_chatbot_message(self, message=None, **kwargs):
        payload = WooSimpleChatbotService(request.env).get_reply(message)
        return {
            "intent": payload.get("intent", "fallback"),
            "reply": payload.get(
                "reply",
                "I'm here to help with WooCommerce connector information such as orders, products, inventory, and sync status.",
            ),
        }
