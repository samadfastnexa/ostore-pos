/** @odoo-module **/

import { registry } from "@web/core/registry";
import { browser } from "@web/core/browser/browser";

// Remove Odoo-branded entries from the user menu: "Documentation", "Support"
// and "My Odoo.com Account" all point at odoo.com, which has no place in a
// white-labeled product sold to retailers. Preferences, Shortcuts and Log out
// stay. Done in a service so it runs after web has registered its items.
//
// This is trademark/branding only. The copyright and LGPL notice in
// Settings > About are deliberately preserved -- see backend/about.xml.
const posRetailHideOdooLinksService = {
    start() {
        const userMenu = registry.category("user_menuitems");
        for (const key of ["documentation", "support", "odoo_account"]) {
            if (userMenu.contains(key)) {
                userMenu.remove(key);
            }
        }

        // Default browser-tab title when no action is open ("Odoo").
        browser.document.title = browser.document.title.replace(/\bOdoo\b/g, "OStore");
    },
};

registry.category("services").add("pos_retail_hide_odoo_links", posRetailHideOdooLinksService);
