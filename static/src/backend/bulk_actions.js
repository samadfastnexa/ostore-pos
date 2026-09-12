/** @odoo-module **/

// Bulk Download PDF and Share on WhatsApp actions on every list view that
// has reports registered in the posRetailReportRegistry.  Patches the
// standard ListController to inject two buttons beside Odoo's native
// action dropdown whenever at least one row is ticked.
//
// Single selection (one record ticked) works identically: the same two
// buttons appear. No separate "detail page" path is needed.

import { patch } from "@web/core/utils/patch";
import { ListController } from "@web/views/list/list_controller";
import { useService } from "@web/core/utils/hooks";
import { _t } from "@web/core/l10n/translation";
import { posRetailReportRegistry } from "./report_registry";

patch(ListController.prototype, {
    setup() {
        super.setup(...arguments);
        this._posRetailActionService = useService("action");
        this._posRetailNotification = useService("notification");
    },

    // ── Helpers ──────────────────────────────────────────────────────────

    get posRetailReportConfig() {
        try {
            return posRetailReportRegistry.get(this.props.resModel);
        } catch {
            return null;
        }
    },

    get posRetailSelectedIds() {
        return this.model.root.selection.map((r) => r.resId);
    },

    // ── Download PDF ────────────────────────────────────────────────────

    async posRetailDownloadPdf() {
        const config = this.posRetailReportConfig;
        if (!config || !config.reports.length) return;
        const ids = this.posRetailSelectedIds;
        if (!ids.length) return;

        // If there is only one report, use it directly; otherwise use the first.
        const report = config.reports[0];
        // Use Odoo's action service to trigger the report, which handles
        // both single and multi-record cases natively.
        this._posRetailActionService.doAction({
            type: "ir.actions.report",
            report_type: "qweb-pdf",
            report_name: report.name,
            report_file: report.name,
            name: report.label,
            data: { ids },
        });
    },

    // ── WhatsApp Share ──────────────────────────────────────────────────

    async posRetailShareWhatsApp() {
        const config = this.posRetailReportConfig;
        if (!config || !config.reports.length) return;
        const ids = this.posRetailSelectedIds;
        if (!ids.length) return;

        const report = config.reports[0];
        // For WhatsApp: generate the PDF and open wa.me link.
        // Build the PDF URL for all selected IDs.
        const pdfUrl = `/report/pdf/${report.name}/${ids.join(",")}`;

        // Try fetching the PDF and sharing via navigator.share if available.
        const canShareFiles =
            typeof navigator !== "undefined" && !!navigator.share && !!navigator.canShare;

        if (canShareFiles) {
            try {
                const res = await fetch(pdfUrl, { credentials: "same-origin" });
                if (res.ok) {
                    const blob = await res.blob();
                    const file = new File(
                        [blob],
                        `${report.label.replace(/[\\/]/g, "-")}.pdf`,
                        { type: "application/pdf" }
                    );
                    if (navigator.canShare({ files: [file] })) {
                        await navigator.share({
                            files: [file],
                            title: report.label,
                        });
                        return;
                    }
                }
            } catch (err) {
                if (err && err.name === "AbortError") return;
                console.warn("pos_retail: bulk WhatsApp share failed", err);
            }
        }

        // Fallback: open wa.me with text only.
        const text = encodeURIComponent(
            `*${report.label}*\n${ids.length} record(s) selected`
        );
        window.open(`https://wa.me/?text=${text}`, "_blank", "noopener,noreferrer");
    },
});
