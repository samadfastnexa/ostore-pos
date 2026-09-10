/** @odoo-module **/

import { patch } from "@web/core/utils/patch";
import { _t } from "@web/core/l10n/translation";
import { LoginScreen } from "@point_of_sale/app/screens/login_screen/login_screen";

// "Backend" is developer's English on the one screen a cashier reads before
// their shift starts, and it names a place they may well have no business in:
// on a branch till the button leads to an office screen their account can
// barely open.
//
// "Back Office" replaced it and was rejected too, which is the useful part:
// that is retail-software jargon, and someone who has not worked in retail
// software does not know what is behind it either.
//
// Both names now, because the shop asked for both and the reason is sound:
// staff here do not share one vocabulary, and a button on a lock screen has
// to be recognised by whoever is standing at it, not be elegant. Two familiar
// words beat one word half of them would have to guess at.
patch(LoginScreen.prototype, {
    get backBtnName() {
        return _t("Admin Panel / Control Center");
    },

    // Which shop am I standing in, and which till is this?
    //
    // The screen showed a clock, a PIN box and a logo. On a single-shop
    // business that is enough. On a chain where every branch owns its own
    // catalogue, customers and staff, it is not: the same logo appears on
    // every till, so nothing on screen distinguished Bahria's counter from
    // Uthal's.
    //
    // That is not cosmetic. Staff belong to ONE company, so a PIN that is
    // correct at one till is genuinely unknown at another -- and the screen
    // gave the cashier no way to tell which one they were at. An afternoon
    // was lost to exactly that: a correct PIN, typed at a till that had
    // never heard of that employee, reported only "PIN not found".
    get posRetailBranchName() {
        return this.pos.config.company_id?.name || this.pos.company?.name || "";
    },

    get posRetailRegisterName() {
        return this.pos.config.name || "";
    },

    // Whether the till is mid-day or waiting to be opened. The button below
    // already says Open Register or Unlock Register, but that is a verb on a
    // button; this states the fact, which is what someone arriving at a
    // counter wants to know before they touch anything.
    get posRetailSessionState() {
        const session = this.pos.session;
        if (!session || !session.id) {
            return _t("Not open yet");
        }
        return session.state === "opened" ? _t("Open") : _t("Waiting to be opened");
    },

    // The staff this till will accept, by name.
    //
    // Deliberately names them rather than counting them. A count answers a
    // question nobody has; the names answer the one actually being asked,
    // which is "should my PIN work here". An employee who is not on this
    // list cannot sign in at this till no matter what they type, because a
    // register only loads employees of its own company.
    //
    // No PINs, obviously. The whole point of a PIN is that it is not on the
    // screen everybody can see.
    get posRetailCashierNames() {
        const employees = this.pos.models["hr.employee"]?.getAll?.() || [];
        return employees
            .map((employee) => employee.name)
            .filter(Boolean)
            .sort((a, b) => a.localeCompare(b));
    },
});
