/** @odoo-module **/

import { Component } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { session } from "@web/session";

// "Back to Till", in the top bar of a back office opened from a till by PIN.
//
// Without it a cashier who came here from the counter has no obvious way
// back, and the obvious-looking one -- Log out -- used to lock the kiosk link
// on that device. The route it calls signs the cashier out without that lock
// and hands the device back to its till account.
//
// Registered only when the session actually came from a till, so it never
// appears in an ordinary office login where it would lead nowhere.
export class PosRetailBackToTill extends Component {
    static template = "pos_retail.BackToTill";
    static props = {};

    goBack() {
        window.location.href = "/pos_retail/back_to_till";
    }
}

if (session.pos_retail_from_till) {
    registry.category("systray").add("pos_retail.back_to_till", {
        Component: PosRetailBackToTill,
    }, { sequence: 1 });
}
