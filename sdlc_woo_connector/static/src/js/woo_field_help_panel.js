/** @odoo-module **/
import { registry } from "@web/core/registry";
import { Component, useState } from "@odoo/owl";
import { standardWidgetProps } from "@web/views/widgets/standard_widget_props";

export class WooFieldHelpPanel extends Component {
    static template = "woo_connector.WooFieldHelpPanel";
    static props = {
        ...standardWidgetProps,
        title: { type: String, optional: true },
        only_with_help: { type: Boolean, optional: true },
        default_collapsed: { type: Boolean, optional: true },
        auto_collapse_threshold: { type: Number, optional: true },
    };
    static defaultProps = {
        title: "Fields and their uses :-",
        only_with_help: false,
        default_collapsed: false,
        auto_collapse_threshold: 30,
    };

    setup() {
        this.state = useState({
            collapsed:
                this.props.default_collapsed ||
                this.fieldEntries.length > this.props.auto_collapse_threshold,
        });
    }

    get fieldEntries() {
        const record = this.props.record;
        if (!record) {
            return [];
        }
        const activeFields = record.activeFields || {};
        const fieldDefs = record.fields || {};
        const seen = new Set();
        const entries = [];
        for (const name of Object.keys(activeFields)) {
            if (seen.has(name)) continue;
            seen.add(name);
            const def = fieldDefs[name] || {};
            const active = activeFields[name] || {};
            const label = active.string || def.string || name;
            const help = active.help || def.help || "";
            if (this.props.only_with_help && !help) {
                continue;
            }
            entries.push({
                name,
                label,
                help: help || this._fallbackDescription(name, def),
            });
        }
        return entries;
    }

    _fallbackDescription(name, def) {
        const typeWord = {
            many2one: "linked record",
            one2many: "list of related records",
            many2many: "multiple linked records",
            selection: "selection value",
            boolean: "toggle",
            date: "date",
            datetime: "date and time",
            integer: "number",
            float: "number",
            monetary: "monetary amount",
            char: "text",
            text: "long text",
            html: "rich text",
            binary: "file",
        }[def.type] || "value";
        return `Displays ${(def.string || name).toLowerCase()} (${typeWord}).`;
    }

    toggle() {
        this.state.collapsed = !this.state.collapsed;
    }
}

registry.category("view_widgets").add("woo_field_help", {
    component: WooFieldHelpPanel,
    extractProps: ({ attrs }) => ({
        title: attrs.title,
        only_with_help: attrs.only_with_help === "1" || attrs.only_with_help === "true",
        default_collapsed: attrs.default_collapsed === "1" || attrs.default_collapsed === "true",
        auto_collapse_threshold: attrs.auto_collapse_threshold ? Number(attrs.auto_collapse_threshold) : undefined,
    }),
});
