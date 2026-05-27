"""Graceful fallback when ``wkhtmltopdf`` is missing.

BUG-39: clicking *Print* on any QWeb-PDF report (Delivery Slip, etc.) on a
machine that does not have ``wkhtmltopdf`` installed shows the warning
"Unable to find Wkhtmltopdf on this system. The report will be shown in
html." and leaves the page blank because the front-end report dispatcher
tries the PDF route first and the HTML fallback iframe is not always
initialised cleanly afterwards.

This override flips the report type to ``qweb-html`` *up front* whenever
wkhtmltopdf is unavailable, so the Odoo client renders the report
in-line as HTML in the standard report viewer. The user can then save it
as a real PDF using the browser's built-in *Print → Save as PDF* (or
press Ctrl+P).

Installing ``wkhtmltopdf 0.12.6.1`` (patched-qt build) is still the
preferred fix because it produces server-rendered PDFs with the correct
report layout. This override only kicks in when the binary is missing.
"""

import logging

from odoo import models

_logger = logging.getLogger(__name__)


class IrActionsReport(models.Model):
    _inherit = "ir.actions.report"

    def report_action(self, docids, data=None, config=True):
        action = super().report_action(docids, data=data, config=config)
        if not isinstance(action, dict):
            return action
        if action.get("report_type") != "qweb-pdf":
            return action
        try:
            state = self.get_wkhtmltopdf_state()
        except Exception:  # pragma: no cover - defensive
            state = "ok"
        if state == "install":
            _logger.info(
                "wkhtmltopdf is not installed; serving %s as HTML so the "
                "user can print to PDF from the browser.",
                self.report_name or self.name,
            )
            action["report_type"] = "qweb-html"
        return action
