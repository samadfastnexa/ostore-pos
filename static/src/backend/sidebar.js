/** @odoo-module **/

import { Component, onMounted, onWillUnmount, useState } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { browser } from "@web/core/browser/browser";
import { useBus, useService } from "@web/core/utils/hooks";

const STORAGE_KEY = "pos_retail_sidebar_collapsed";
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
        this.state = useState({
            collapsed: browser.localStorage.getItem(STORAGE_KEY) === "1",
        });

        // The menu service announces app changes on the bus; re-render so the
        // active app and its sections stay in step with the action.
        useBus(this.env.bus, "MENUS:APP-CHANGED", () => this.render(true));

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

    onClickMenu(menu) {
        // selectMenu is a no-op for a menu with no action (a pure grouping
        // node), so fall through to its first actionable child instead.
        if (!menu.actionID && this.hasChildren(menu)) {
            const target = menu.childrenTree.find((child) => child.actionID);
            if (target) {
                this.menuService.selectMenu(target);
            }
            return;
        }
        this.menuService.selectMenu(menu);
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
