/** @odoo-module **/

import { Component, useState } from "@odoo/owl";
import { Dialog } from "@web/core/dialog/dialog";
import { _t } from "@web/core/l10n/translation";

/**
 * Confirmation dialog before sharing a document on WhatsApp.
 *
 * Shows the partner name, document type, phone number (editable), and a
 * Share / Cancel pair.  The caller receives the (possibly corrected) phone
 * number back through the onConfirm prop.
 *
 * Props:
 *   partnerName  String   "ABC Traders"
 *   documentName String   "Customer Ledger"
 *   phone        String   "+92 300 1234567"  (pre-filled, editable)
 *   onConfirm    Function (phone) => void
 *   close        Function from Dialog
 */
export class WhatsAppShareDialog extends Component {
    static template = "pos_retail.WhatsAppShareDialog";
    static components = { Dialog };
    static props = {
        partnerName: { type: String, optional: true },
        documentName: { type: String, optional: true },
        phone: { type: String, optional: true },
        onConfirm: { type: Function },
        close: { type: Function },
    };

    setup() {
        this.state = useState({
            phone: this.props.phone || "",
        });
    }

    onShare() {
        this.props.onConfirm(this.state.phone);
        this.props.close();
    }
}
