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
// software does not know what is behind it either. "Admin Panel" is the
// phrase the people using this shop actually say, so it is the one that
// belongs on the button -- not the one that reads best to whoever wrote it.
patch(LoginScreen.prototype, {
    get backBtnName() {
        return _t("Admin Panel");
    },
});
