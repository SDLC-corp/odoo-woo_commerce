/** @odoo-module **/
/**
 * BUG-39: when ``wkhtmltopdf`` is not installed, every QWeb-PDF report
 * (Delivery Slip, Invoice, Sale Quotation, …) goes through this sequence in
 * Odoo's action dispatcher:
 *
 *   1. ``downloadReport`` calls ``/report/check_wkhtmltopdf`` -> returns
 *      ``"install"``;
 *   2. it shows the sticky warning toast "Unable to find Wkhtmltopdf on this
 *      system. The report will be shown in html.";
 *   3. control falls back to ``_executeReportClientAction`` which opens an
 *      iframe pointing at ``/report/html/...``.
 *
 * In practice steps (2) + (3) race and the user sees the toast on top of a
 * blank iframe area. Installing ``wkhtmltopdf`` is the proper fix; this
 * patch is a graceful degradation when the binary is missing.
 *
 * We intercept ``actionService.start`` so the returned action manager's
 * ``doAction`` pre-checks the wkhtmltopdf status. When the binary is
 * missing or broken, the report action's ``report_type`` is rewritten
 * from ``"qweb-pdf"`` to ``"qweb-html"`` *before* the dispatcher branches.
 * The dispatcher then routes straight to the HTML viewer — no toast, no
 * blank page, no race. The user can press Ctrl+P in the HTML view to
 * produce a real PDF via the browser's own engine.
 */
import { actionService } from "@web/webclient/actions/action_service";

const originalStart = actionService.start;
if (!actionService.__wooPdfFallbackPatched) {
    actionService.start = function patchedStart(env) {
        const manager = originalStart.call(this, env);
        const rpc = env.services && env.services.rpc;
        let wkhtmltopdfStatusProm = null;
        const getWkhtmltopdfStatus = () => {
            if (!rpc) {
                return Promise.resolve("ok");
            }
            wkhtmltopdfStatusProm =
                wkhtmltopdfStatusProm || rpc("/report/check_wkhtmltopdf");
            return wkhtmltopdfStatusProm.catch(() => "ok");
        };
        const originalDoAction = manager.doAction.bind(manager);
        manager.doAction = async function patchedDoAction(action, options) {
            if (
                action &&
                typeof action === "object" &&
                action.type === "ir.actions.report" &&
                action.report_type === "qweb-pdf"
            ) {
                try {
                    const status = await getWkhtmltopdfStatus();
                    if (status === "install" || status === "broken") {
                        action = { ...action, report_type: "qweb-html" };
                    }
                } catch (_err) {
                    // Best-effort: if the status check itself errors, leave
                    // the action untouched and let Odoo's default flow run.
                }
            }
            return originalDoAction(action, options);
        };
        return manager;
    };
    actionService.__wooPdfFallbackPatched = true;
}
