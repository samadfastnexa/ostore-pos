/** @odoo-module **/

import { Component } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { _t } from "@web/core/l10n/translation";
import { standardWidgetProps } from "@web/views/widgets/standard_widget_props";

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

    get shareText() {
        const rec = this.props.record;
        const lines = ["*" + this.shareTitle + "*"];
        if (rec.data.amount_total !== undefined && rec.fields.amount_total) {
            lines.push(_t("Total: %s", String(rec.data.amount_total)));
        }
        return lines.join("\n");
    }

    openTextFallback(number) {
        const text = encodeURIComponent(this.shareText);
        const url = number
            ? `https://wa.me/${number}?text=${text}`
            : `https://wa.me/?text=${text}`;
        const win = window.open(url, "_blank", "noopener,noreferrer");
        if (!win) {
            this.notification.add(
                _t("WhatsApp could not be opened. Allow pop-ups for this site and try again."),
                { type: "warning" }
            );
        }
    }

    async onClick() {
        const rec = this.props.record;
        // An unsaved document has no id to render a PDF from.
        if (!rec.resId) {
            await rec.save();
            if (!rec.resId) {
                return;
            }
        }

        // Decide the route BEFORE any await: window.open after an await is
        // outside the user-gesture window and gets blocked as a pop-up. The
        // same mistake made the POS button do nothing at first.
        const canShareFiles =
            typeof navigator !== "undefined" && !!navigator.share && !!navigator.canShare;
        if (!canShareFiles) {
            this.notification.add(
                _t("This device cannot attach files to WhatsApp, so a text summary is being sent instead. Attaching the PDF needs https."),
                { type: "info" }
            );
            // The phone lookup is an RPC, and window.open after an await is
            // blocked as a pop-up. An earlier version solved that by opening
            // WITHOUT the number -- which meant the one path production (plain
            // http) will ever take never used the customer's phone at all, and
            // every send started at WhatsApp's contact picker. Instead: claim
            // the window synchronously, inside the click, then steer it once
            // the number is known.
            const win = window.open("about:blank", "_blank");
            const { phone, phoneCode } = await this.fetchShareData();
            const number = this.normalize(phone, phoneCode);
            const text = encodeURIComponent(this.shareText);
            const url = number
                ? `https://wa.me/${number}?text=${text}`
                : `https://wa.me/?text=${text}`;
            if (win) {
                win.location = url;
            } else {
                this.notification.add(
                    _t("WhatsApp could not be opened. Allow pop-ups for this site and try again."),
                    { type: "warning" }
                );
            }
            return;
        }

        try {
            const { phone, phoneCode } = await this.fetchShareData();
            const number = this.normalize(phone, phoneCode);
            const res = await fetch(`/report/pdf/${this.props.report}/${rec.resId}`, {
                credentials: "same-origin",
            });
            if (!res.ok) {
                this.openTextFallback(number);
                return;
            }
            const blob = await res.blob();
            const file = new File(
                [blob],
                `${this.shareTitle.replace(/[\\/]/g, "-")}.pdf`,
                { type: "application/pdf" }
            );
            if (!navigator.canShare({ files: [file] })) {
                this.openTextFallback(number);
                return;
            }
            await navigator.share({
                files: [file],
                title: this.shareTitle,
                text: this.shareText,
            });
        } catch (err) {
            if (err && err.name === "AbortError") {
                return; // the user closed the share sheet on purpose
            }
            console.warn("pos_retail: WhatsApp share failed", err);
            this.notification.add(
                _t("Could not share the PDF. Check the report prints normally from the Print menu."),
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
