/** @odoo-module **/

import { patch } from "@web/core/utils/patch";
import { _t } from "@web/core/l10n/translation";
import { rpc } from "@web/core/network/rpc";
import { Navbar } from "@point_of_sale/app/components/navbar/navbar";
import { makeAwaitable } from "@point_of_sale/app/utils/make_awaitable_dialog";
import { NumberPopup } from "@point_of_sale/app/components/popups/number_popup/number_popup";
import { AlertDialog } from "@web/core/confirmation_dialog/confirmation_dialog";

// "Back Office" in the till's menu, opened as the cashier with their PIN.
//
// A kiosk till is signed in as the shared till account, so simply leaving the
// POS would put every cashier into the back office with that account's rights,
// identical for all of them. This asks for the cashier's PIN and has the
// server sign the browser in as their OWN user, so what they see is exactly
// what their role allows.
//
// The PIN is asked for again rather than trusting whoever is already the
// cashier on screen. A till is often left unlocked mid-shift, and whoever
// walks up to it should not inherit the previous cashier's back office.
patch(Navbar.prototype, {
    get posRetailShowBackOffice() {
        return Boolean(this.pos.getCashier()?._can_back_office);
    },

    async posRetailOpenBackOffice() {
        const cashier = this.pos.getCashier();
        if (!cashier) {
            return;
        }
        const pin = await makeAwaitable(this.dialog, NumberPopup, {
            title: _t("PIN for %s", cashier.name),
            subtitle: _t("The back office will open as you."),
            // Masked, like the lock screen. Somebody at the next counter can
            // see the screen as easily as the keypad.
            formatDisplayedValue: (value) => value.replace(/./g, "•"),
        });
        if (!pin) {
            return;
        }

        let result;
        try {
            result = await rpc("/pos_retail/back_office/pin", {
                config_id: this.pos.config.id,
                employee_id: cashier.id,
                pin: String(pin),
            });
        } catch (error) {
            result = {
                ok: false,
                message: error?.data?.message || error?.message || _("Please try again."),
            };
        }

        if (!result?.ok) {
            this.dialog.add(AlertDialog, {
                title: _t("Back office not opened"),
                body: result?.message || _t("Please try again."),
            });
            return;
        }
        // A full navigation, not a client-side route. The browser now holds a
        // different user's session, and the POS in memory was loaded for the
        // till account; carrying on inside it would mix the two.
        window.location.href = result.redirect;
    },
});
