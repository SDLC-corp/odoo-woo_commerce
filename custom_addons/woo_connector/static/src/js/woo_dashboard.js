import { registry } from "@web/core/registry";
import { Component, useState, onMounted, onWillUnmount } from "@odoo/owl";
import { rpc } from "@web/core/network/rpc";
import { useService } from "@web/core/utils/hooks";

export class WooDashboard extends Component {
    setup() {
        this.refreshIntervalMs = 60000;
        this.refreshTimer = null;
        this.refreshQueued = false;
        this.busService = useService("bus_service");
        this.onDashboardBusMessage = this.onDashboardBusMessage.bind(this);
        this.state = useState({
            range: "30",
            instanceId: "all",
            instances: [],
            initialLoad: true,
            loading: false,
            data: {
                totals: {
                    instances: 0,
                    customers: 0,
                    categories: 0,
                    coupons: 0,
                    products: 0,
                    orders: 0,
                    total_sales: 0,
                    net_sales: 0,
                },
                intervals: [],
                categories: [],
                products: [],
                order_status: {},
                payments: [],
                gift_cards: {
                    total: 0,
                    used: 0,
                    pending: 0,
                    expired: 0,
                    no_balance: 0,
                },
                recent_orders: [],
                meta: {
                    date_from: "",
                    date_to: "",
                    instance_name: "",
                    is_all: true,
                },
                ai_insight: {
                    summary_text: "",
                    status: "draft",
                    generated_at: "",
                    actionable_recommendations: [],
                    predicted_top_products_to_restock: [],
                    products_at_risk_of_stockout: [],
                    low_sales_products: [],
                    sales_summary: {},
                },
            },
            viz: {
                statusRows: [],
                paymentRows: [],
                revenuePct: 0,
            },
        });

        onMounted(async () => {
            await this.loadInstances();
            await this.loadData();
            if (this.busService) {
                this.busService.subscribe("woo_dashboard_update", this.onDashboardBusMessage);
                this.busService.start();
            }
            this.startAutoRefresh();
        });

        onWillUnmount(() => {
            if (this.busService) {
                this.busService.unsubscribe("woo_dashboard_update", this.onDashboardBusMessage);
            }
            this.stopAutoRefresh();
        });
    }

    async loadInstances() {
        const res = await rpc("/web/dataset/call_kw", {
            model: "woo.dashboard",
            method: "get_instances",
            args: [],
            kwargs: {},
        });
        this.state.instances = res || [];
    }

    async loadData() {
        this.state.loading = true;
        const fast = this.state.initialLoad;

        try {
            const res = await rpc("/web/dataset/call_kw", {
                model: "woo.dashboard",
                method: "get_analytics_data",
                args: [],
                kwargs: {
                    range: this.state.range,
                    instance_id: this.state.instanceId,
                    fast,
                },
            });

            this.state.data = {
                totals: res?.totals || {
                    instances: 0,
                    customers: 0,
                    categories: 0,
                    coupons: 0,
                    products: 0,
                    orders: 0,
                    total_sales: 0,
                    net_sales: 0,
                },
                intervals: res?.intervals || [],
                categories: res?.categories || [],
                products: res?.products || [],
                order_status: res?.order_status || {},
                payments: res?.payments || [],
                gift_cards: res?.gift_cards || {
                    total: 0,
                    used: 0,
                    pending: 0,
                    expired: 0,
                    no_balance: 0,
                },
                recent_orders: res?.recent_orders || [],
                meta: res?.meta || {
                    date_from: "",
                    date_to: "",
                    instance_name: "",
                    is_all: true,
                },
                ai_insight: res?.ai_insight || {
                    summary_text: "",
                    status: "draft",
                    generated_at: "",
                    actionable_recommendations: [],
                    predicted_top_products_to_restock: [],
                    products_at_risk_of_stockout: [],
                    low_sales_products: [],
                    sales_summary: {},
                },
            };

            this.state.viz = this.buildViz(this.state.data);
        } finally {
            this.state.loading = false;
        }

        if (fast) {
            this.state.initialLoad = false;
            await this.loadData();
        }
    }

    async syncNow() {
        this.state.loading = true;

        await rpc("/web/dataset/call_kw", {
            model: "woo.dashboard",
            method: "manual_sync",
            args: [],
            kwargs: {
                instance_id: this.state.instanceId,
            },
        });

        await this.loadData();
    }

    async generateInsights() {
        this.state.loading = true;
        try {
            const result = await rpc("/web/dataset/call_kw", {
                model: "woo.dashboard",
                method: "generate_ai_insights",
                args: [],
                kwargs: {
                    range: this.state.range,
                    instance_id: this.state.instanceId,
                },
            });
            this.state.data.ai_insight = result || {};
            await this.loadData();
        } finally {
            this.state.loading = false;
        }
    }

    startAutoRefresh() {
        this.stopAutoRefresh();
        this.refreshTimer = setInterval(async () => {
            if (!this.state.loading) {
                await this.loadData();
            }
        }, this.refreshIntervalMs);
    }

    stopAutoRefresh() {
        if (this.refreshTimer) {
            clearInterval(this.refreshTimer);
            this.refreshTimer = null;
        }
    }

    async onDashboardBusMessage(payload) {
        const instanceId = payload?.instance_id;
        const shouldRefresh =
            this.state.instanceId === "all" ||
            !instanceId ||
            String(this.state.instanceId) === String(instanceId);

        if (shouldRefresh) {
            await this.refreshFromPush();
        }
    }

    async refreshFromPush() {
        if (this.state.loading || this.refreshQueued) {
            return;
        }
        this.refreshQueued = true;
        try {
            await this.loadData();
        } finally {
            this.refreshQueued = false;
        }
    }

    buildViz(data) {
        const totals = data?.totals || {};
        const totalOrders = totals.orders || 0;
        const totalSales = totals.total_sales || 0;
        const totalCoupons = totals.coupons || 0;
        const totalProducts = totals.products || 0;
        const status = data?.order_status || {};
        const payments = data?.payments || [];
        const intervals = data?.intervals || [];

        const statusRows = [
            { key: "pending", label: "Pending" },
            { key: "processing", label: "Processing" },
            { key: "completed", label: "Completed" },
            { key: "cancelled", label: "Cancelled" },
            { key: "refunded", label: "Refunded" },
            { key: "failed", label: "Failed" },
        ].map((row) => {
            const value = Number(status[row.key] || 0);
            const pct = totalOrders ? Math.round((value / totalOrders) * 100) : 0;
            return { ...row, value, pct };
        });

        return {
            statusRows,
            revenuePct: totalSales ? 100 : 0,
        };
    }
}

WooDashboard.template = "woo_dashboard_template";
registry.category("actions").add("woo_dashboard", WooDashboard);
