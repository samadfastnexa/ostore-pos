/** @odoo-module **/

import { patch } from "@web/core/utils/patch";
import { ProductScreen } from "@point_of_sale/app/screens/product_screen/product_screen";

// Brand is the fourth thing a shopkeeper reaches for after name, SKU and
// barcode -- "the Sonex basin", "that Philips bulb" -- and on a catalogue of
// thousands it is often the only word anyone remembers at the counter. Core
// searches name / default_code / barcode only, so a brand-only search came
// back empty even though brand_id sits right there on the template.
//
// Server side: this domain is sent to load_product_from_pos, where the relation
// can be walked. product.brand IS loaded into the POS now (pos_session.py), so
// a client-side brand match over already-loaded products could be added on top
// of this -- the server pass is what reaches products not yet loaded.
patch(ProductScreen.prototype, {
    loadProductFromDBDomain(searchProductWord) {
        const domain = super.loadProductFromDBDomain(searchProductWord);

        // Core returns one OR group followed by two AND-ed guards
        // (available_in_pos, sale_ok). Widening the OR group means adding one
        // "|" in front and appending the new leaf to the end of that group,
        // leaving the guards untouched. Bail out unchanged if core ever
        // reshapes the domain, so brand search degrades to core behaviour
        // instead of building a domain the server would reject.
        const guards = domain.slice(-2);
        const shapeIsKnown =
            guards.length === 2 &&
            guards.every((leaf) => Array.isArray(leaf) && leaf.length === 3) &&
            guards[0][0] === "available_in_pos" &&
            guards[1][0] === "sale_ok";
        if (!shapeIsKnown) {
            return domain;
        }

        return [
            "|",
            ...domain.slice(0, -2),
            ["brand_id", "ilike", searchProductWord],
            ...guards,
        ];
    },
});
