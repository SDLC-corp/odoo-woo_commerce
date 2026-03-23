/** @odoo-module **/

import { Component, onWillUnmount, useState } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { rpc } from "@web/core/network/rpc";
import { useService } from "@web/core/utils/hooks";

export class WooSimpleChatbot extends Component {
    setup() {
        this.menuService = useService("menu");
        this.state = useState({
            isVisible: this.isWooCommerceApp(),
            isOpen: false,
            isLoading: false,
            input: "",
            quickActions: [
                "Today's Orders",
                "Recent Orders",
                "Low Stock Products",
                "Top Selling Products",
                "Sync Status",
            ],
            messages: [
                { role: "bot", text: "Hello. Ask me about low stock, recent orders, top products, or sync status." },
            ],
        });

        this.onAppChanged = this.onAppChanged.bind(this);
        this.env.bus.addEventListener("MENUS:APP-CHANGED", this.onAppChanged);
        onWillUnmount(() => {
            this.env.bus.removeEventListener("MENUS:APP-CHANGED", this.onAppChanged);
        });
    }

    isWooCommerceApp() {
        const currentApp = this.menuService.getCurrentApp();
        return !!(currentApp && currentApp.name === "WooCommerce");
    }

    onAppChanged() {
        const isVisible = this.isWooCommerceApp();
        this.state.isVisible = isVisible;
        if (!isVisible) {
            this.state.isOpen = false;
        }
    }

    toggleOpen() {
        if (!this.state.isVisible) {
            return;
        }
        this.state.isOpen = !this.state.isOpen;
    }

    closePopup() {
        this.state.isOpen = false;
    }

    onInput(ev) {
        this.state.input = ev.target.value;
    }

    async sendQuickAction(ev) {
        this.state.input = ev.currentTarget.dataset.prompt || "";
        await this.sendMessage();
    }

    async sendMessage() {
        const message = (this.state.input || "").trim();
        if (!message || this.state.isLoading) {
            return;
        }

        this.state.messages.push({ role: "user", text: message });
        this.state.input = "";
        this.state.isLoading = true;

        try {
            const response = await rpc("/ai/chatbot/message", { message });
            this.state.messages.push({
                role: "bot",
                text: (response && response.reply) || "I'm here to help with WooCommerce connector questions.",
            });
        } catch (error) {
            console.error("Simple chatbot request failed", error);
            this.state.messages.push({
                role: "bot",
                text: "I could not process that right now. Please try again.",
            });
        } finally {
            this.state.isLoading = false;
        }
    }

    async onKeydown(ev) {
        if (ev.key === "Enter" && !ev.shiftKey) {
            ev.preventDefault();
            await this.sendMessage();
        }
    }
}

WooSimpleChatbot.template = "sdlc_woo_connector.SimpleChatbot";
registry.category("main_components").add("woo_simple_chatbot", { Component: WooSimpleChatbot });
