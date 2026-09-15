/** @odoo-module **/

import { Component, useState, onMounted, onWillUnmount, useExternalListener } from "@odoo/owl";
import { Dialog } from "@web/core/dialog/dialog";
import { _t } from "@web/core/l10n/translation";
import { usePos } from "@point_of_sale/app/hooks/pos_hook";
import { PosStore } from "@point_of_sale/app/services/pos_store";
import { LoginScreen } from "@point_of_sale/app/screens/login_screen/login_screen";
import { patch } from "@web/core/utils/patch";

/**
 * Cashier Welcome Back Page / Modal displayed every time the register is unlocked.
 * Shows cashier name, branch, register, live Pakistan Standard Time (PKT),
 * role indicator, and quick "Start Selling" dismissal.
 */
export class CashierWelcomePopup extends Component {
    static template = "pos_retail.CashierWelcomePopup";
    static components = { Dialog };
    static props = {
        close: Function,
        onClose: { type: Function, optional: true },
        cashier: { type: Object, optional: true },
    };

    setup() {
        this.pos = usePos();
        this.state = useState({
            currentTime: this.formatCurrentPktTime(),
            secondsLeft: 4,
        });

        // Listen for keyboard input (Enter, Space, Esc or barcode scanning) to dismiss immediately
        useExternalListener(window, "keydown", this.onKeydown.bind(this));

        let timer = null;
        let clockTimer = null;

        onMounted(() => {
            clockTimer = setInterval(() => {
                this.state.currentTime = this.formatCurrentPktTime();
            }, 1000);

            timer = setInterval(() => {
                this.state.secondsLeft -= 1;
                if (this.state.secondsLeft <= 0) {
                    clearInterval(timer);
                    this.closePopup();
                }
            }, 1000);
        });

        onWillUnmount(() => {
            if (timer) clearInterval(timer);
            if (clockTimer) clearInterval(clockTimer);
            if (this.props.onClose) {
                try {
                    this.props.onClose();
                } catch (_) {}
            }
        });
    }

    formatCurrentPktTime() {
        try {
            return (
                new Intl.DateTimeFormat("en-PK", {
                    timeZone: "Asia/Karachi",
                    weekday: "short",
                    day: "numeric",
                    month: "short",
                    year: "numeric",
                    hour: "2-digit",
                    minute: "2-digit",
                    second: "2-digit",
                    hour12: true,
                }).format(new Date()) + " (PKT)"
            );
        } catch (_) {
            const now = new Date();
            return now.toLocaleTimeString() + " PKT";
        }
    }

    get cashier() {
        return this.props.cashier || this.pos.getCashier() || this.pos.user;
    }

    get cashierName() {
        return this.cashier?.name || _t("Cashier");
    }

    get cashierInitials() {
        const name = this.cashierName.trim();
        if (!name) return "C";
        const parts = name.split(/\s+/);
        if (parts.length > 1) {
            return (parts[0][0] + parts[parts.length - 1][0]).toUpperCase();
        }
        return name.slice(0, 2).toUpperCase();
    }

    get avatarUrl() {
        const cashier = this.cashier;
        if (cashier && cashier.id) {
            if (this.pos.config.module_pos_hr) {
                return `/web/image/hr.employee.public/${cashier.id}/avatar_128`;
            }
            return `/web/image/res.users/${cashier.id}/avatar_128`;
        }
        return "";
    }

    get branchName() {
        return (
            this.pos.config.company_id?.name ||
            this.pos.company?.name ||
            _t("Main Store")
        );
    }

    get registerName() {
        return this.pos.config.name || _t("Register 1");
    }

    get roleName() {
        const cashier = this.cashier;
        if (cashier?._can_admin_panel || cashier?._role === "manager") {
            return _t("Manager");
        }
        return _t("Cashier");
    }

    onKeydown(ev) {
        if (ev.key === "Enter" || ev.key === " " || ev.key === "Escape") {
            ev.preventDefault();
            ev.stopPropagation();
            this.closePopup();
        } else if (ev.key && ev.key.length === 1 && !ev.ctrlKey && !ev.altKey && !ev.metaKey) {
            // Hardware barcode scan or cashier started typing: dismiss immediately so cart is unblocked
            this.closePopup();
        }
    }

    closePopup() {
        if (this.props.onClose) {
            try {
                this.props.onClose();
            } catch (_) {}
        }
        this.props.close();
    }

    startSelling() {
        this.closePopup();
    }
}

// Hook PosStore to trigger Welcome Back popup whenever register unlocks from LoginScreen
patch(PosStore.prototype, {
    async showLoginScreen() {
        this.posRetailPendingWelcome = null;
        this.posRetailWelcomePopupActive = false;
        return super.showLoginScreen(...arguments);
    },

    setCashier(user) {
        const fromLogin = this.router?.state?.current === "LoginScreen";
        if (fromLogin && user) {
            this.posRetailPendingWelcome = user;
        }
        return super.setCashier(...arguments);
    },

    navigate(routeName, routeParams) {
        const fromLogin = this.router?.state?.current === "LoginScreen";
        const res = super.navigate(...arguments);
        if (fromLogin && routeName !== "LoginScreen") {
            const cashier = this.posRetailPendingWelcome || this.getCashier();
            this.posRetailPendingWelcome = null;
            if (cashier) {
                this.posRetailScheduleWelcomePopup(cashier);
            }
        }
        return res;
    },

    posRetailScheduleWelcomePopup(cashier) {
        if (this.posRetailWelcomePopupActive) {
            return;
        }
        this.posRetailWelcomePopupActive = true;
        setTimeout(() => {
            if (this.router?.state?.current !== "LoginScreen") {
                this.dialog.add(CashierWelcomePopup, {
                    cashier: cashier || this.getCashier(),
                    onClose: () => {
                        this.posRetailWelcomePopupActive = false;
                    },
                });
            } else {
                this.posRetailWelcomePopupActive = false;
            }
        }, 120);
    },
});

// Also hook LoginScreen cashierLogIn as safety net across both HR and non-HR POS modes
patch(LoginScreen.prototype, {
    cashierLogIn() {
        super.cashierLogIn(...arguments);
        const cashier = this.pos.getCashier();
        if (cashier) {
            this.pos.posRetailScheduleWelcomePopup(cashier);
        }
    },
});
