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
    setup() {
        super.setup(...arguments);
        this._posRetailInitDetails();
        console.log("%c[POS-DIAG] LoginScreen setup() complete", "background: #2e7d32; color: #fff; padding: 2px 6px;", {
            branch: this.posRetailBranchName,
            register: this.posRetailRegisterName,
            sessionIsOpen: this.posRetailSessionIsOpen,
            sessionState: this.posRetailSessionState,
            cashiersCount: this.posRetailCashierNames.length,
            cashiers: this.posRetailCashierNames,
        });
    },

    _posRetailInitDetails() {
        // Cache static information once during setup to avoid repeating store iteration
        // and string sorting every 500ms when core useTime() ticks
        try {
            const companyId = this.pos?.config?.company_id?.id || this.pos?.config?.company_id;
            const companyRec = companyId ? this.pos?.models?.["res.company"]?.get(companyId) : null;
            this._cachedBranchName = companyRec?.name || this.pos?.config?.company_id?.name || this.pos?.company?.name || "";
        } catch (_) {
            this._cachedBranchName = this.pos?.company?.name || "";
        }

        this._cachedRegisterName = this.pos?.config?.name || "";

        const flatten = (value) =>
            (value || "").toLowerCase().replace(/[^a-z0-9]/g, "");
        const register = flatten(this._cachedRegisterName);
        this._cachedShowRegisterName = Boolean(register) && register !== flatten(this._cachedBranchName);

        try {
            const employees = this.pos?.models?.["hr.employee"]?.getAll?.() || [];
            this._cachedCashierNames = employees
                .map((employee) => employee?.name)
                .filter(Boolean)
                .sort((a, b) => a.localeCompare(b));
        } catch (_) {
            this._cachedCashierNames = [];
        }
    },

    get backBtnName() {
        if (this.pos?.login && this.pos?.config?.module_pos_hr) {
            return _t("Discard");
        }
        return _t("Admin Panel / Control Center");
    },

    get posRetailBranchName() {
        return this._cachedBranchName || "";
    },

    get posRetailRegisterName() {
        return this._cachedRegisterName || "";
    },

    get posRetailSessionState() {
        return this.posRetailSessionIsOpen ? _t("Open") : _t("Not open yet");
    },

    get posRetailSessionIsOpen() {
        const session = this.pos?.session;
        return Boolean(session && session.id && session.state === "opened");
    },

    get posRetailShowRegisterName() {
        return this._cachedShowRegisterName;
    },

    get posRetailCashierNames() {
        return this._cachedCashierNames || [];
    },
});
