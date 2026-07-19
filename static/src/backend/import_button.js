/** @odoo-module **/

import { patch } from "@web/core/utils/patch";
import { registry } from "@web/core/registry";
import { exprToBoolean } from "@web/core/utils/strings";
import { ListController } from "@web/views/list/list_controller";
import { KanbanController } from "@web/views/kanban/kanban_controller";

// A visible "Import" button beside New on every list and kanban, instead of
// the entry buried in the cog menu. Visibility and the launched action both
// mirror base_import's cog item (import_records.js) exactly, so the button
// appears precisely where "Import records" used to and nowhere else --
// views flagged import="0" or create="0" (e.g. read-only report lists) still
// show nothing.
const posRetailImportable = {
    posRetailCanImport() {
        const config = this.env.config;
        return (
            config.actionType === "ir.actions.act_window" &&
            ["list", "kanban"].includes(config.viewType) &&
            exprToBoolean(config.viewArch.getAttribute("import"), true) &&
            exprToBoolean(config.viewArch.getAttribute("create"), true)
        );
    },
    posRetailOnImport() {
        const { context, resModel } = this.env.searchModel;
        this.actionService.doAction({
            type: "ir.actions.client",
            tag: "import",
            params: { active_model: resModel, context },
        });
    },
};

patch(ListController.prototype, posRetailImportable);
patch(KanbanController.prototype, posRetailImportable);

// With a labelled button in plain sight, the cog's own "Import records" line
// is a duplicate; drop it. Done in a service so it runs after base_import has
// registered the entry (removing at module-load time would race its add()).
const posRetailImportButtonService = {
    start() {
        const cogMenu = registry.category("cogMenu");
        if (cogMenu.contains("import-menu")) {
            cogMenu.remove("import-menu");
        }
    },
};

registry.category("services").add("pos_retail_import_button", posRetailImportButtonService);
