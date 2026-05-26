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
    };
    static defaultProps = {
        title: "Fields and their uses :-",
        only_with_help: false,
    };

    setup() {
        this.state = useState({ collapsed: false });
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
        const niceName = (def.string || name).toLowerCase();
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
        return `Displays ${niceName} (${typeWord}).`;
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
    }),
});
