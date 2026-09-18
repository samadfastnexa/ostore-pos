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

            // 1. Native mobile share sheet: share PDF file ONLY
            if (typeof navigator !== "undefined" && typeof navigator.share === "function" && typeof navigator.canShare === "function") {
                try {
                    const file = new File([blob], filename, { type: "application/pdf" });
                    if (navigator.canShare({ files: [file] })) {
                        await navigator.share({
                            files: [file],
                            title: report.label,
                        });
                        this.notification.add(_t("Bulk PDF shared successfully on WhatsApp."), { type: "success" });
                        return;
                    }
                } catch (err) {
                    if (err && err.name === "AbortError") {
                        return; // User canceled share sheet
                    }
                    console.warn("pos_retail: bulk WhatsApp native share failed, falling back", err);
                }
            }

            // 2. Desktop fallback: automatically download the PDF file to user's computer
            try {
                const blobUrl = URL.createObjectURL(blob);
                const a = document.createElement("a");
                a.href = blobUrl;
                a.download = filename;
                document.body.appendChild(a);
                a.click();
                document.body.removeChild(a);
                setTimeout(() => URL.revokeObjectURL(blobUrl), 2000);
            } catch (dlErr) {
                console.warn("pos_retail: bulk PDF download failed", dlErr);
            }

            // 3. Open WhatsApp Web
            window.open("https://web.whatsapp.com/", "_blank", "noopener,noreferrer");

            this.notification.add(
                _t("PDF sharing is not supported by this browser. The bulk PDF has been downloaded so you can attach it manually in WhatsApp."),
                { type: "warning" }
            );
        } catch (err) {
            console.warn("pos_retail: bulk WhatsApp share error", err);
            this.notification.add(
                err?.message || _t("Could not generate or share bulk PDF. Please check connection."),
                { type: "danger" }
            );
        }
    },
});
