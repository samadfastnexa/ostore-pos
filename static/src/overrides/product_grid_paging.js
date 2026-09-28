/** @odoo-module **/

import { patch } from "@web/core/utils/patch";
import { PosStore } from "@point_of_sale/app/services/pos_store";
import { ProductScreen } from "@point_of_sale/app/screens/product_screen/product_screen";

// Core never puts more than 100 products on the grid: filterExcludedProducts
// (pos_store.js) stops collecting at 100, and it only sorts AFTER that cut. So
// "All" showed some arbitrary 100 of a 659-product catalogue, re-sorted by name,
// and the rest could only be found by searching -- the same inside Paints or
// Electric, each of which has more than 100 products on its own.
//
// Lifting the cap outright would draw every card on every change to the cart,
// and each card prices itself through the tax engine (product_card.js). So the
// grid pages instead: all matching products are filtered and sorted, the first
// GRID_PAGE are drawn, and another page is added whenever the cashier scrolls
// near the bottom. Because the cut is taken from the sorted list, a new page
// always lands below what is already on screen instead of shuffling into it.

// Also the size of core's cap, which filterExcludedProducts relies on below.
const GRID_PAGE = 100;

patch(PosStore.prototype, {
    async setup() {
        // Set before core's setup so the lazy product getters find it on their
        // first run and track it: raising it later then refreshes the grid.
        this.posRetailGridLimit = GRID_PAGE;
        return await super.setup(...arguments);
    },

    posRetailResetGrid() {
        if (this.posRetailGridLimit !== GRID_PAGE) {
            this.posRetailGridLimit = GRID_PAGE;
        }
    },

    // Core filters and caps in the same loop. Handing it batches no larger than
    // its cap means the cap never fires, while which products are excluded
    // (unavailable, restricted categories, special products) stays core's call.
    filterExcludedProducts(products) {
        const kept = [];
        let batch = [];
        for (const product of products) {
            batch.push(product);
            if (batch.length === GRID_PAGE) {
                kept.push(...super.filterExcludedProducts(batch));
                batch = [];
            }
        }
        if (batch.length) {
            kept.push(...super.filterExcludedProducts(batch));
        }
        return kept;
    },

    get productsToDisplay() {
        return super.productsToDisplay.slice(0, this.posRetailGridLimit);
    },

    // With "group by category" on, core filters each category's list on its
    // own, so the limit has to be spent across the groups in the order they
    // are drawn. Without grouping this is a single group, already cut above.
    get productToDisplayByCateg() {
        let room = this.posRetailGridLimit;
        const shown = [];
        for (const [categId, products] of super.productToDisplayByCateg) {
            if (room <= 0) {
                break;
            }
            shown.push([categId, products.slice(0, room)]);
            room -= products.length;
        }
        return shown;
    },

    setSelectedCategory() {
        super.setSelectedCategory(...arguments);
        // A new category starts from the top, one page long.
        this.posRetailResetGrid();
    },
});

patch(ProductScreen.prototype, {
    setup() {
        super.setup(...arguments);
        // Every visit (a new sale after payment, coming back from Orders)
        // starts with a light grid, not however far the last one was scrolled.
        this.pos.posRetailResetGrid();

        // Core's handler only cancels a long-press when the grid moves; keep it
        // and check for the bottom alongside it.
        const coreOnScroll = this.onScroll;
        this.onScroll = (ev) => {
            coreOnScroll(ev);
            this.posRetailGrowGridNearBottom(ev.target);
        };
    },

    posRetailGrowGridNearBottom(scroller) {
        if (!scroller) {
            return;
        }
        // Start the next page while a screenful is still left, so the cashier
        // does not hit the bottom and wait.
        const remaining = scroller.scrollHeight - scroller.scrollTop - scroller.clientHeight;
        if (remaining > scroller.clientHeight) {
            return;
        }
        // Count the cards actually drawn, not the store's list. Fewer than the
        // limit means either every product is already showing, or the last
        // page has not rendered yet -- asking again in either case would only
        // redraw the same grid, once per scroll event.
        const drawn = scroller.getElementsByClassName("product").length;
        if (drawn < this.pos.posRetailGridLimit) {
            return;
        }
        this.pos.posRetailGridLimit += GRID_PAGE;
    },
});
