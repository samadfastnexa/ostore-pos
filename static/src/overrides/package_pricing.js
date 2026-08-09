/** @odoo-module **/

import { patch } from "@web/core/utils/patch";
import { PosOrderline } from "@point_of_sale/app/models/pos_order_line";

// Per-package pricing.
//
// Scanning a package barcode is already handled by core: it finds the base
// product and sets the line quantity from the package unit (a 5 kg bag gives
// qty 5), which is what keeps one inventory serving every package size.
//
// What core cannot know is that a bulk package is usually priced BELOW the
// unit price times its quantity -- a 5 kg bag at Rs 1650 rather than 5 x 350.
// So after core has done its work, apply the package's own price. It is
// applied per unit (package price / package quantity) precisely so the
// quantity, and therefore the stock movement, stays untouched: qty 5 at
// Rs 330 totals the Rs 1650 on the shelf label.
patch(PosOrderline.prototype, {
    setOptions(options) {
        super.setOptions(...arguments);

        const code = options?.code;
        if (!code) {
            return;
        }
        // Core matches packagings on `code`; the product lookup uses
        // `base_code` (GS1 strips prefixes), so accept either.
        const packages = this.models["product.uom"];
        const pkg =
            packages.getBy("barcode", code.code) ||
            (code.base_code && packages.getBy("barcode", code.base_code));

        if (!pkg || pkg.product_id?.id !== this.product_id?.id) {
            return;
        }
        this.pos_retail_package_id = pkg;
        if (pkg.unit_price) {
            this.setUnitPrice(pkg.unit_price);
            this.price_type = "manual";
        }
    },
});
