/** @odoo-module **/

import { Component, onMounted, onWillUnmount, useState } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { browser } from "@web/core/browser/browser";
import { useBus, useService } from "@web/core/utils/hooks";

const STORAGE_KEY = "pos_retail_sidebar_collapsed";
const SECTIONS_KEY = "pos_retail_sidebar_closed_sections";
const BODY_CLASS = "pos-retail-side-collapsed";

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
