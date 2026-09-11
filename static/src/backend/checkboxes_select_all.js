/** @odoo-module **/

import { _t } from "@web/core/l10n/translation";
import { registry } from "@web/core/registry";
import {
    Many2ManyCheckboxesField,
    many2ManyCheckboxesField,
} from "@web/views/fields/many2many_checkboxes/many2many_checkboxes_field";

// Checkboxes with "Select all" and "Clear" for the section they sit in.
//
// Building a role meant ticking permissions one at a time, and the catalogue
// is now nearly sixty entries across ten sections. An owner setting up an
// "Admin" role was clicking every box in Inventory, then every box in
// Purchases, and so on -- which is exactly the kind of tedium that ends with
// one box missed and a role that quietly cannot do one thing.
//
// Scoped to the SECTION, deliberately, not to the whole field. Each section
// on the role form is the same many2many rendered through its own domain, so
// "select all" here means "everything in Products", never "everything in the
// catalogue". Granting the whole catalogue at once is a much bigger decision,
// and it is kept to its own button with a confirmation on the form header.
export class PosRetailCheckboxesSelectAll extends Many2ManyCheckboxesField {
    static template = "pos_retail.CheckboxesSelectAll";

    get posRetailAllSelected() {
        const items = this.items || [];
        return items.length > 0 && items.every((item) => this.isSelected(item));
    }

    get posRetailNoneSelected() {
        return (this.items || []).every((item) => !this.isSelected(item));
    }

    posRetailSelectAll() {
        for (const item of this.items || []) {
            if (!this.isSelected(item)) {
                this.onChange(item[0], true);
            }
        }
        // Committed now, not on the parent's half-second debounce. isSelected
        // reads the record's current ids, so until the commit lands every box
        // would still show its old state -- and a person who clicked "Select
        // all" and saw nothing tick would reasonably click it again.
        this.commitChanges();
    }

    posRetailClearAll() {
        for (const item of this.items || []) {
            if (this.isSelected(item)) {
                this.onChange(item[0], false);
            }
        }
        this.commitChanges();
    }
}

registry.category("fields").add("pos_retail_checkboxes_select_all", {
    ...many2ManyCheckboxesField,
    component: PosRetailCheckboxesSelectAll,
    displayName: _t("Checkboxes with Select all"),
});
