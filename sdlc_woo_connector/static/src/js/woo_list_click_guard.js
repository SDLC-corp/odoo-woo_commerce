/** @odoo-module **/

import { patch } from "@web/core/utils/patch";
import { ListController } from "@web/views/list/list_controller";

// Odoo 16's patch() takes a name and reaches the patched method through this._super.
patch(ListController.prototype, "sdlc_woo_connector.ListController", {
    async openRecord(record, force = false) {
        const model = this.props?.resModel;
        if (model === "woo.product.sync") {
            return;
        }
        return this._super(record, force);
    },
});
