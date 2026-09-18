/** @odoo-module **/

import { Component, useState } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { _t } from "@web/core/l10n/translation";
import { standardWidgetProps } from "@web/views/widgets/standard_widget_props";
import { formatMonetary } from "@web/views/fields/formatters";

// "Send on WhatsApp" for backend documents: quotations, purchase orders,
// invoices, payment receipts, delivery slips and the khata statement.
//
// One widget, parameterised by the report to send:
//     <widget name="pos_retail_whatsapp" report="sale.report_saleorder"/>
// registered in view_widgets, which is how Odoo 19 puts a custom client-side
// control into a form view (the same registry core uses for attach_document).
// A plain <button type="object"> will not do: it calls Python, and the share
// sheet (navigator.share) only exists in the browser.
//
// Sharing itself mirrors the POS receipt button. The wa.me URL scheme carries
// text and nothing else, so the actual PDF can only travel through the OS
// share sheet -- and that needs a secure context, which localhost is and the
// production bare-IP http server is not. There the fallback runs: WhatsApp
// opens with a text summary, and the cashier is told why there is no file.
export class PosRetailWhatsappWidget extends Component {
    static template = "pos_retail.WhatsappWidget";
    static props = {
        ...standardWidgetProps,
        report: { type: String },
        title: { type: String, optional: true },
    };

    setup() {
        this.orm = useService("orm");
        this.notification = useService("notification");
        // The PDF render takes seconds; without feedback the button looks
        // dead and gets clicked repeatedly, queueing a render per click.
        this.wa = useState({ busy: false });
    }

    /** International digits for wa.me: country code first, no plus. */
    normalize(raw, phoneCode) {
        let digits = String(raw || "").replace(/\D/g, "");
        if (!digits) {
            return "";
        }
        if (digits.startsWith("00")) {
            return digits.slice(2);
        }
        const code = String(phoneCode || "").replace(/\D/g, "");
        if (digits.startsWith("0")) {
            return code ? code + digits.slice(1) : digits.slice(1);
        }
        if (code && digits.length <= 10 && !digits.startsWith(code)) {
            return code + digits;
        }
        return digits;
    }

    /**
     * Partner phone + dialling code, fetched on click rather than at render:
     * the partner's phone is rarely among the form's own fields, so it has to
     * be read anyway, and three tiny reads on a click cost nothing while reads
     * on every form render would.
     */
    async fetchShareData() {
        const rec = this.props.record;
        const partnerField = rec.data.partner_id ? "partner_id" : false;
        let phone = "";
        let phoneCode = "";
        let partnerId = false;
        if (partnerField) {
            partnerId = rec.data[partnerField].id ?? rec.data[partnerField][0];
        } else if (rec.resModel === "res.partner") {
            partnerId = rec.resId;
        }
        if (partnerId) {
            const [p] = await this.orm.read("res.partner", [partnerId],
                ["phone", "mobile", "country_id"]);
            phone = p.phone || p.mobile || "";
            let countryId = p.country_id && p.country_id[0];
            if (!countryId) {
                // No country on the contact: use the document's company's.
                const companyId = rec.data.company_id
                    ? (rec.data.company_id.id ?? rec.data.company_id[0])
                    : false;
                if (companyId) {
                    const [c] = await this.orm.read("res.company", [companyId], ["country_id"]);
                    countryId = c.country_id && c.country_id[0];
                }
            }
            if (countryId) {
                const [country] = await this.orm.read("res.country", [countryId], ["phone_code"]);
                phoneCode = country.phone_code || "";
            }
        }
        return { phone, phoneCode };
    }

    get shareTitle() {
        const rec = this.props.record;
        return `${this.props.title || _t("Document")} ${rec.data.display_name || rec.data.name || ""}`.trim();
    }

    buildShareText(pdfUrl = "") {
        const rec = this.props.record;
        const lines = ["*" + this.shareTitle + "*"];

        const candidates = [
            ["pos_outstanding_balance", _t("Amount owed")],
            ["amount_residual", _t("Still due")],
            ["amount_total", _t("Total")],
        ];
        for (const [field, label] of candidates) {
            const value = rec.data[field];
            if (rec.fields[field] && value !== undefined && value !== null) {
                lines.push(`${label}: ${this.formatAmount(value)}`);
                break;
            }
        }
        if (pdfUrl) {
            lines.push("");
            lines.push("📄 *Download Official PDF:*");
            lines.push(pdfUrl);
        }
        lines.push("");
        lines.push("Thank you!");
        return lines.join("\n");
    }

    get shareText() {
        return this.buildShareText();
    }

    /** The figure as the shop writes it, falling back to the bare number if
     *  the record carries no currency to format against. */
    formatAmount(value) {
        const currencyId = this.props.record.data.currency_id?.[0];
        try {
            return formatMonetary(value, { currencyId });
        } catch {
            return String(value);
        }
    }

    async onClick() {
        if (this.wa.busy) {
            return;
        }
        this.wa.busy = true;
        try {
            await this._onClick();
        } finally {
            this.wa.busy = false;
        }
    }

    async _onClick() {
        const rec = this.props.record;
        if (!rec.resId) {
            await rec.save();
            if (!rec.resId) {
                return;
            }
        }

        // Claim popup window synchronously to prevent desktop browser blocking
        const canShareFiles =
            typeof navigator !== "undefined" && !!navigator.share && !!navigator.canShare;
        let win = null;
        if (!canShareFiles) {
            win = window.open("about:blank", "_blank");
        }

        try {
            const { phone, phoneCode } = await this.fetchShareData();
            const number = this.normalize(phone, phoneCode);

            // Fetch public PDF URL
            let pdfUrl = "";
            try {
                const info = await this.orm.call("pos.retail.report.service", "get_doc_share_info", [
                    rec.resModel,
                    rec.resId,
                ]);
                pdfUrl = info?.pdf_url || "";
            } catch (infoErr) {
                console.warn("pos_retail: could not get doc share info", infoErr);
            }

            const text = this.buildShareText(pdfUrl);
            const filename = `${this.shareTitle.replace(/[\\/]/g, "-")}.pdf`;

            // Fetch PDF blob
            let blob = null;
            try {
                const res = await fetch(`/report/pdf/${this.props.report}/${rec.resId}`, {
                    credentials: "same-origin",
                });
                if (res.ok) {
                    blob = await res.blob();
                }
            } catch (blobErr) {
                console.warn("pos_retail: could not fetch PDF blob", blobErr);
            }

            // 1. Native mobile share sheet: share PDF file ONLY
            if (canShareFiles && blob) {
                try {
                    const file = new File([blob], filename, { type: "application/pdf" });
                    if (navigator.canShare({ files: [file] })) {
                        await navigator.share({
                            files: [file],
                            title: this.shareTitle,
                        });
                        this.notification.add(_t("Document PDF shared successfully on WhatsApp."), { type: "success" });
                        return;
                    }
                } catch (err) {
                    if (err && err.name === "AbortError") {
                        return;
                    }
                    console.warn("pos_retail: native share failed, falling back", err);
                }
            }

            // 2. Desktop fallback: automatically download the PDF file to user's computer
            if (blob) {
                try {
                    const blobUrl = URL.createObjectURL(blob);
                    const a = document.createElement("a");
                    a.href = blobUrl;
                    a.download = filename;
                    document.body.appendChild(a);
                    a.click();
                    document.body.removeChild(a);
                    URL.revokeObjectURL(blobUrl);
                } catch (dlErr) {
                    console.warn("pos_retail: automatic PDF download failed", dlErr);
                }
            }

            // 3. Open WhatsApp Web directly to customer's chat
            const url = number
                ? `https://web.whatsapp.com/send?phone=${number}`
                : `https://web.whatsapp.com/`;

            if (win && !win.closed) {
                win.location = url;
            } else {
                window.open(url, "_blank", "noopener,noreferrer");
            }

            this.notification.add(
                _t("PDF downloaded! WhatsApp opened. Please attach or drag & drop the PDF into the chat."),
                { type: "success" }
            );
        } catch (err) {
            console.warn("pos_retail: WhatsApp share error", err);
            if (win && !win.closed) {
                win.close();
            }
            this.notification.add(
                _t("Could not share on WhatsApp. Please check network connection."),
                { type: "warning" }
            );
        }
    }
}

export const posRetailWhatsappWidget = {
    component: PosRetailWhatsappWidget,
    extractProps: ({ attrs }) => ({
        report: attrs.report,
        title: attrs.title,
    }),
};

registry.category("view_widgets").add("pos_retail_whatsapp", posRetailWhatsappWidget);
