/** @odoo-module **/

import { _t } from "@web/core/l10n/translation";
import { Component } from "@odoo/owl";
import { Dialog } from "@web/core/dialog/dialog";
import { usePos } from "@point_of_sale/app/hooks/pos_hook";
import { useService } from "@web/core/utils/hooks";
import { PosRetailCustomerHistory } from "@pos_retail/overrides/customer_history";

// Customer profile shown at the till: what this customer is worth, what they
// owe, and how much credit they have left. The figures come from the session
// payload (see res_partner._load_pos_data_fields), so opening the card costs
// no round trip and works offline.
export class PosRetailCustomerProfile extends Component {
    static template = "pos_retail.CustomerProfile";
    static components = { Dialog };
    static props = {
        partner: Object,
        close: Function,
    };

    setup() {
        this.pos = usePos();
        this.dialog = useService("dialog");
    }

    get partner() {
        return this.props.partner;
    }

    /** Counter-facing tags: "wholesale", "pays on time", "deliver to home". */
    get tags() {
        return this.partner.category_id || [];
    }

    showHistory() {
        this.props.close();
        this.dialog.add(PosRetailCustomerHistory, { partner: this.partner });
    }

    formatCurrency(value) {
        return this.pos.env.utils.formatCurrency(value || 0);
    }

    /** "2 days ago" reads better than a timestamp on a card meant to be glanced at. */
    get lastPurchase() {
        const raw = this.partner.pos_last_purchase_date;
        if (!raw) {
            return _t("Never");
        }
        const then = typeof raw === "string" ? new Date(raw.replace(" ", "T") + "Z") : raw.toJSDate?.() ?? new Date(raw);
        const days = Math.floor((Date.now() - then.getTime()) / 86400000);
        if (days <= 0) {
            return _t("Today");
        }
        if (days === 1) {
            return _t("Yesterday");
        }
        if (days < 30) {
            return _t("%s days ago", days);
        }
        const months = Math.floor(days / 30);
        return months === 1 ? _t("A month ago") : _t("%s months ago", months);
    }

    get hasCreditLimit() {
        return Boolean(this.partner.pos_credit_limit);
    }

    get overLimit() {
        return this.hasCreditLimit && this.partner.pos_credit_available < 0;
    }
}
