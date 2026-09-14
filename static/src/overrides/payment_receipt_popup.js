/** @odoo-module **/

import { Component } from "@odoo/owl";
import { Dialog } from "@web/core/dialog/dialog";
import { _t } from "@web/core/l10n/translation";
import { usePos } from "@point_of_sale/app/hooks/pos_hook";

/**
 * Customer Payment Receipt Modal with complete audit breakdown and print support.
 * Implements Requirement 7.
 */
export class PaymentReceiptPopup extends Component {
    static template = "pos_retail.PaymentReceiptPopup";
    static components = { Dialog };
    static props = {
        close: Function,
        receipt: Object,
    };

    setup() {
        this.pos = usePos();
    }

    get receipt() {
        return this.props.receipt || {};
    }

    printReceipt() {
        window.print();
    }
}
