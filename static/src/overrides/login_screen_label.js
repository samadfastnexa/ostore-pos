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
});
