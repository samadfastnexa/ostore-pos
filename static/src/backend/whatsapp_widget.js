/** @odoo-module **/

import { Component, useState } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { _t } from "@web/core/l10n/translation";
import { standardWidgetProps } from "@web/views/widgets/standard_widget_props";
import { formatMonetary } from "@web/views/fields/formatters";
import { openWhatsAppChoice } from "./whatsapp_choice_dialog";

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
        this.dialog = useService("dialog");
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

        try {
            const filename = `${this.shareTitle.replace(/[\\/]/g, "-")}.pdf`;

            // Run phone lookup and PDF generation concurrently to preserve browser user activation
            const [shareData, res] = await Promise.all([
                this.fetchShareData().catch((err) => {
                    console.warn("pos_retail: could not fetch share data", err);
                    return { phone: "", phoneCode: "" };
                }),
                fetch(`/report/pdf/${this.props.report}/${rec.resId}`, { credentials: "same-origin" }),
            ]);

            if (!res.ok) {
                throw new Error(_t("Could not generate document PDF (Status %s).", res.status));
            }
            const blob = await res.blob();
            if (!blob || blob.size === 0) {
                throw new Error(_t("Generated document PDF was empty."));
            }

            const number = this.normalize(shareData.phone, shareData.phoneCode);

            // Prompt every time: WhatsApp Web vs WhatsApp App (zero saved selection)
            const shared = await openWhatsAppChoice(this.dialog, number, { blob, filename });
            if (shared) {
                this.notification.add(
                    _t("Document PDF processed for WhatsApp sharing."),
                    { type: "info" }
                );
            }
        } catch (err) {
            console.warn("pos_retail: WhatsApp share error", err);
            this.notification.add(
                err?.message || _t("Could not generate or share document PDF. Please check connection."),
                { type: "danger" }
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
