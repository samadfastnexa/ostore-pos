import { patch } from "@web/core/utils/patch";
import { user } from "@web/core/user";
import { CompanySelector } from "@web/webclient/switch_company_menu/switch_company_menu";
import { SwitchCompanyItem } from "@web/webclient/switch_company_menu/switch_company_item";

/**
 * Keep at least one company switched on.
 *
 * Core lets you untick every company at once and offers to confirm it. Ticking
 * a company off also ticks off every branch under it, so in a one-shop setup --
 * MURSHID Company with Murshad Bahria Branch below it -- the parent's checkbox
 * is really a "turn everything off" button. Confirm that and the whole backend
 * has no company to read through: lists come back empty, the register cannot be
 * opened, and nothing on screen says why.
 *
 * Nobody ever wants that, so the last company standing stops being tickable.
 * Switching between shops still works normally, and so does hiding a branch
 * while another company remains on.
 */

function companyById(companyId) {
    return user.allowedCompaniesWithAncestors.find((c) => c.id === companyId);
}

patch(CompanySelector.prototype, {
    /**
     * How many companies would remain selected if this one were ticked off.
     * Counts the branches that would go with it, the same way core's
     * _deselectCompany recurses through child_ids.
     */
    posRetailRemainingWithout(companyId) {
        const losing = new Set();
        const walk = (id) => {
            if (losing.has(id)) {
                return;
            }
            losing.add(id);
            (companyById(id)?.child_ids || []).forEach(walk);
        };
        walk(companyId);
        return this.selectedCompaniesIds.filter((id) => !losing.has(id)).length;
    },

    /** True when this company is the only thing keeping the session populated. */
    posRetailIsLastStanding(companyId) {
        return this.isCompanySelected(companyId) && this.posRetailRemainingWithout(companyId) === 0;
    },

    switchCompany(mode, companyId) {
        if (mode === "toggle" && this.posRetailIsLastStanding(companyId)) {
            return;
        }
        return super.switchCompany(mode, companyId);
    },

    /**
     * The header's select-all toggle empties the list just as readily -- core
     * unselects everything the moment anything is selected. Let it clear the
     * ones it can and keep the company you are currently in.
     */
    selectAll(companyIds) {
        const before = [...this.selectedCompaniesIds];
        super.selectAll(companyIds);
        if (this.selectedCompaniesIds.length === 0) {
            const keep = before.includes(user.activeCompany.id) ? user.activeCompany.id : before[0];
            if (keep !== undefined) {
                this.selectedCompaniesIds.push(keep);
            }
        }
    },

    /** Last line of defence: never push an empty company set to the server. */
    async apply() {
        if (this.selectedCompaniesIds.length === 0) {
            this.reset();
            return;
        }
        return super.apply();
    },
});

patch(SwitchCompanyItem.prototype, {
    get posRetailIsLocked() {
        return this.companySelector.posRetailIsLastStanding(this.props.company.id);
    },
});
