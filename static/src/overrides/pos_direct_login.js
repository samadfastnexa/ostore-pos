/** @odoo-module **/

import { patch } from "@web/core/utils/patch";
import { PosStore } from "@point_of_sale/app/services/pos_store";

patch(PosStore.prototype, {
    async setup() {
        await super.setup(...arguments);
        this._autoLoginDirectCashier();
    },

    async afterProcessServerData() {
        const res = await super.afterProcessServerData(...arguments);
        this._autoLoginDirectCashier();
        return res;
    },

    checkPreviousLoggedCashier() {
        super.checkPreviousLoggedCashier(...arguments);
        this._autoLoginDirectCashier();
    },

    _autoLoginDirectCashier() {
        if (!this.user?.pos_direct_login) {
            return;
        }

        if (this.config.module_pos_hr) {
            const userId = this.user.id;
            let cashierEmp = this.models["hr.employee"]?.find(
                (emp) => emp.user_id?.id === userId || emp.user_id === userId
            );

            if (!cashierEmp && this.models["hr.employee"]?.length) {
                cashierEmp = this.models["hr.employee"].getFirst();
            }

            if (cashierEmp) {
                this.setCashier(cashierEmp);
                this.hasLoggedIn = true;
                sessionStorage.setItem(`connected_cashier_${this.config.id}`, cashierEmp.id);
            }
        } else {
            this.setCashier(this.user);
            this.hasLoggedIn = true;
        }
    },

    get firstPage() {
        if (this.user?.pos_direct_login) {
            this._autoLoginDirectCashier();
            return this.defaultPage;
        }
        return super.firstPage;
    },

    async handleUrlParams() {
        if (this.user?.pos_direct_login) {
            this._autoLoginDirectCashier();
            if (
                this.router.state.current === "LoginScreen" ||
                this.router.state.current === "SaverScreen"
            ) {
                this.router.navigate(this.defaultPage.page, this.defaultPage.params || {});
                return;
            }
        }
        return await super.handleUrlParams(...arguments);
    },

    shouldShowOpeningControl() {
        if (this.user?.pos_direct_login) {
            return false;
        }
        return super.shouldShowOpeningControl(...arguments);
    },

    get idleTimeout() {
        if (this.user?.pos_direct_login) {
            return [
                {
                    timeout: 300000, // 5 minutes
                    action: () =>
                        this.router.state.current !== "PaymentScreen" &&
                        this.navigate("SaverScreen"),
                },
            ];
        }
        return super.idleTimeout;
    },
});
