/** @odoo-module **/

import { Component, onMounted, onWillUnmount, useState } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { browser } from "@web/core/browser/browser";
import { useBus, useService } from "@web/core/utils/hooks";
import { fuzzyLookup } from "@web/core/utils/search";
import { computeAppsAndMenuItems } from "@web/webclient/menus/menu_helpers";

const STORAGE_KEY = "pos_retail_sidebar_collapsed";
const SECTIONS_KEY = "pos_retail_sidebar_closed_sections";
const BODY_CLASS = "pos-retail-side-collapsed";

// Enough to cover a real query, few enough that the list never scrolls past
// the fold. Beyond a dozen hits the answer is a better search term.
const MAX_RESULTS = 12;

// Left navigation for the back office.
//
// Odoo ships no sidebar at all -- navigation lives in the top bar -- so this is
// a new component rather than a restyle. It is mounted through the
// "main_components" registry instead of by rewriting web.WebClient's template,
// which keeps it clear of core layout changes between versions.
//
// It renders the real menu tree from the menu service: every app, and for the
// app you are in, its own sections. A section that only groups other menus
// becomes a heading, which is what produces the grouped look.
export class PosRetailSidebar extends Component {
    static template = "pos_retail.Sidebar";
    static props = {};

    setup() {
        this.menuService = useService("menu");
        let closedSections = {};
        try {
            closedSections = JSON.parse(browser.localStorage.getItem(SECTIONS_KEY) || "{}") || {};
        } catch {
            closedSections = {};
        }
        this.state = useState({
            collapsed: browser.localStorage.getItem(STORAGE_KEY) === "1",
            // Sections are open unless the user closed them; only closed ids
            // are stored, so new sections (new menus, other apps) start open.
            closedSections,
            // Highlighted leaf. Tracked from sidebar clicks; the menu service
            // has no public "current leaf menu", only the current app.
            activeMenuId: null,
            // Menu search. Odoo has this already, in the command palette --
            // but behind Ctrl+K then "/", which a shopkeeper will never find.
            // The searching is core's; what this adds is a box you can see.
            query: "",
        });

        // The menu service announces app changes on the bus; re-render so the
        // active app and its sections stay in step with the action. A plain
        // render suffices -- deep-forcing (render(true)) re-rendered every
        // child on each app switch for no benefit.
        useBus(this.env.bus, "MENUS:APP-CHANGED", () => this.render());

        onMounted(() => this.syncBodyClass());
        onWillUnmount(() => document.body.classList.remove(BODY_CLASS));
    }

    get apps() {
        return this.menuService.getApps();
    }

    get currentApp() {
        return this.menuService.getCurrentApp();
    }

    /** Sections of the app currently open, as a tree. */
    get sections() {
        const app = this.currentApp;
        if (!app) {
            return [];
        }
        return this.menuService.getMenuAsTree(app.id).childrenTree || [];
    }

    // ------------------------------------------------------------------
    // Search
    // ------------------------------------------------------------------

    get isSearching() {
        return Boolean(this.state.query.trim());
    }

    /**
     * Every menu in the whole database that matches, not just this app's.
     *
     * That is the point of it: a shopkeeper looking for "till sections" does
     * not know it lives under Point of Sale > Configuration, and being made to
     * guess the app first is the problem, not the solution.
     *
     * computeAppsAndMenuItems and fuzzyLookup are core's own -- the same pair
     * behind Ctrl+K -- so ranking and typo tolerance match the rest of Odoo
     * instead of being a second, slightly different search.
     */
    get searchResults() {
        const query = this.state.query.trim();
        if (!query) {
            return [];
        }
        const { apps, menuItems } = computeAppsAndMenuItems(
            this.menuService.getMenuAsTree("root")
        );
        // Path reversed before matching, exactly as menu_providers.js does:
        // it weights the leaf above its ancestors, so typing "categories"
        // ranks "Configuration / Categories" over every menu that merely
        // sits inside an app whose name happens to match.
        const menuHits = fuzzyLookup(query, menuItems, (menu) =>
            (menu.parents + " / " + menu.label).split("/").reverse().join("/")
        );
        const appHits = fuzzyLookup(query, apps, (app) => app.label).map((app) =>
            Object.assign({}, app, { parents: "" })
        );
        return appHits.concat(menuHits).slice(0, MAX_RESULTS);
    }

    clearSearch() {
        this.state.query = "";
    }

    onSearchKeydown(ev) {
        if (ev.key === "Escape") {
            this.clearSearch();
            ev.target.blur();
        } else if (ev.key === "Enter") {
            // Enter opens the top hit, so a search can be finished without
            // ever moving to the mouse.
            const first = this.searchResults[0];
            if (first) {
                this.openResult(first);
            }
        }
    }

    openResult(item) {
        this.state.query = "";
        this.state.activeMenuId = item.id;
        this.menuService.selectMenu(item);
    }

    isCurrentApp(app) {
        return Boolean(this.currentApp && this.currentApp.id === app.id);
    }

    hasChildren(menu) {
        return Boolean(menu.childrenTree && menu.childrenTree.length);
    }

    isSectionOpen(section) {
        return !this.state.closedSections[section.id];
    }

    toggleSection(section) {
        if (this.state.closedSections[section.id]) {
            delete this.state.closedSections[section.id];
        } else {
            this.state.closedSections[section.id] = true;
        }
        browser.localStorage.setItem(SECTIONS_KEY, JSON.stringify(this.state.closedSections));
    }

    isActive(menu) {
        return this.state.activeMenuId === menu.id;
    }

    onClickMenu(menu) {
        // selectMenu is a no-op for a menu with no action (a pure grouping
        // node), so fall through to its first actionable child instead.
        let target = menu;
        if (!menu.actionID && this.hasChildren(menu)) {
            target = menu.childrenTree.find((child) => child.actionID);
            if (!target) {
                return;
            }
        }
        this.state.activeMenuId = target.id;
        this.menuService.selectMenu(target);
    }

    syncBodyClass() {
        document.body.classList.toggle(BODY_CLASS, this.state.collapsed);
    }

    toggle() {
        this.state.collapsed = !this.state.collapsed;
        browser.localStorage.setItem(STORAGE_KEY, this.state.collapsed ? "1" : "0");
        this.syncBodyClass();
    }
}

registry.category("main_components").add("pos_retail.Sidebar", {
    Component: PosRetailSidebar,
});
