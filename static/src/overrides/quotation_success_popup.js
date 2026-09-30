/** @odoo-module **/

import { Component, useState } from "@odoo/owl";
import { Dialog } from "@web/core/dialog/dialog";
import { _t } from "@web/core/l10n/translation";
import { usePos } from "@point_of_sale/app/hooks/pos_hook";
import { useService } from "@web/core/utils/hooks";
import { shareQuotationOnWhatsApp } from "./quotation_modal";
import { PosRetailQuotationModal } from "./quotation_modal";

export class PosRetailQuotationSuccessPopup extends Component {
    static template = "pos_retail.QuotationSuccessPopup";
    static components = { Dialog };
    static props = {
        close: Function,
        quote: Object,
        lines: { type: Array, optional: true },
        isUpdate: { type: Boolean, optional: true },
    };

    setup() {
        this.pos = usePos();
        this.dialog = useService("dialog");
        this.notification = useService("notification");

        this.state = useState({
            sharing: false,
        });
    }

    formatMoney(val) {
        return this.pos.env.utils.formatCurrency(val || 0);
    }

    async onShareWhatsApp() {
        if (this.state.sharing) return;
        this.state.sharing = true;
        try {
            await shareQuotationOnWhatsApp({
                pos: this.pos,
                dialog: this.dialog,
                notification: this.notification,
                quote: this.props.quote,
                lines: this.props.lines,
            });
        } catch (err) {
            console.error("pos_retail: WhatsApp share failed:", err);
            this.notification.add(
                err?.message || _t("Could not share quotation on WhatsApp."),
                { type: "danger" }
            );
        } finally {
            this.state.sharing = false;
        }
    }

    printQuotationPdf() {
        const quote = this.props.quote;
        if (!quote?.id) return;
        const url = `/pos_retail/print_report?report=sale.report_saleorder&id=${quote.id}`;
        let iframe = document.getElementById("pos_retail_direct_print_frame");
        if (!iframe) {
            iframe = document.createElement("iframe");
            iframe.id = "pos_retail_direct_print_frame";
            iframe.style.position = "fixed";
            iframe.style.right = "0";
            iframe.style.bottom = "0";
            iframe.style.width = "0";
            iframe.style.height = "0";
            iframe.style.border = "0";
            document.body.appendChild(iframe);
        }
        iframe.src = url;
        this.notification.add(_t("Sending %(quote)s to printer...", { quote: quote.name }), {
            type: "info",
        });
    }

    onViewAllQuotations() {
        this.props.close();
        this.dialog.add(PosRetailQuotationModal, {});
    }
}
