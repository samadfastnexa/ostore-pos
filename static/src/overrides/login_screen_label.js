/** @odoo-module **/

import { patch } from "@web/core/utils/patch";
import { _t } from "@web/core/l10n/translation";
import { LoginScreen } from "@point_of_sale/app/screens/login_screen/login_screen";

// "Backend" is developer's English. It is the one word on the lock screen a
// cashier reads before their shift starts, and it names a place they may well
// have no business in: on a branch till the button leads to an office screen
// their account can barely open.
//
// Renamed to what the button actually does. "Back Office" is the phrase this
// shop already uses for the same place in its own help text elsewhere, so the
// screen and the documentation now agree.
patch(LoginScreen.prototype, {
    get backBtnName() {
        return _t("Back Office");
    },
});
