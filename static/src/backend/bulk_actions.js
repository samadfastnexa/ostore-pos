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
import { openWhatsAppChoice } from "./whatsapp_choice_dialog";

patch(ListController.prototype, {
    setup() {
        super.setup(...arguments);
        this._posRetailActionService = useService("action");
        this._posRetailNotification = useService("notification");
        this._posRetailDialog = useService("dialog");
    },

    // ── Helpers ──────────────────────────────────────────────────────────

    get posRetailReportConfig() {
        try {
            if (!this.props || !this.props.resModel) return null;
            return posRetailReportRegistry.get(this.props.resModel);
        } catch {
            return null;
        }
    },

    get posRetailSelectedIds() {
        try {
            return (this.model?.root?.selection || []).map((r) => r.resId);
        } catch {
            return [];
        }
    },

    get posRetailHasSelectedReports() {
        try {
            return !!(this.posRetailReportConfig && (this.posRetailSelectedIds || []).length);
        } catch {
            return false;
        }
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
        const filename = `${report.label.replace(/[\\/]/g, "-")}.pdf`;
        const pdfUrl = `/report/pdf/${report.name}/${ids.join(",")}`;

        try {
            const res = await fetch(pdfUrl, { credentials: "same-origin" });
            if (!res.ok) {
                throw new Error(_t("Could not generate bulk PDF report (Status %s).", res.status));
            }
            const blob = await res.blob();
            if (!blob || blob.size === 0) {
                throw new Error(_t("Generated bulk PDF was empty."));
            }

            // Prompt every time: WhatsApp Web vs WhatsApp App (zero saved selection)
            const shared = await openWhatsAppChoice(this._posRetailDialog, "", { blob, filename });
            if (shared) {
                this.notification.add(
                    _t("Bulk PDF processed for WhatsApp sharing."),
                    { type: "info" }
                );
            }
        } catch (err) {
            console.warn("pos_retail: bulk WhatsApp share error", err);
            this.notification.add(
                err?.message || _t("Could not generate or share bulk PDF. Please check connection."),
                { type: "danger" }
            );
        }
    },
});
