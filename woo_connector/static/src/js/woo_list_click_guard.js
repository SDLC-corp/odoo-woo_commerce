import { patch } from "@web/core/utils/patch";
import { ListController } from "@web/views/list/list_controller";

patch(ListController.prototype, {
    async openRecord(record, force = false) {
        const model = this.props?.resModel;
        if (model === "woo.product.sync") {
            return;
        }
        return super.openRecord(record, force);
    },
});
