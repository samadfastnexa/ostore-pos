import { patch } from "@web/core/utils/patch";
import { user } from "@web/core/user";
import {
    CompanySelector,
    SwitchCompanyMenu,
    systrayItem,
} from "@web/webclient/switch_company_menu/switch_company_menu";
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

/**
 * Take the switcher away entirely from anyone who works in one shop.
 *
 * Core decides "nothing to switch between" by counting
 * allowedCompaniesWithAncestors, and that includes
 * disallowed_ancestor_companies -- the parent, carried along purely so the
 * tree has a heading. A cashier granted one branch therefore counts as two, so
 * the control stays live and opens on MURSHID Company sitting above their
 * shop: a company they cannot select, cannot use, and have no reason to know
 * exists.
 *
 * Disabling the button is not enough on its own. The component also registers
 * a "Switch Company" command on alt+shift+u (switch_company_menu.js:211) whose
 * action calls dropdown.open() directly, and that path never consults
 * isSingleCompany -- so the dropdown opens anyway from the keyboard or the
 * command palette, greyed button or not.
 *
 * Not mounting the component closes every route at once: no button, no hotkey,
 * no command-palette entry, because useCommand only registers on mount.
 * Mutating isDisplayed is how core itself drops a systray item
 * (navbar.js:82), and navbar.js:111 re-reads it on every render.
 *
 * The mobile burger menu needs nothing: it already guards on
 * allowedCompanies.length > 1 (burger_menu.xml:26), which is the correct test.
 */
systrayItem.isDisplayed = () => user.allowedCompanies.length > 1;

patch(SwitchCompanyMenu.prototype, {
    get isSingleCompany() {
        return user.allowedCompanies.length <= 1;
    },
});
