/** @odoo-module **/

import { patch } from "@web/core/utils/patch";
import { FormController } from "@web/views/form/form_controller";

// A line or two at the top of a form saying what the screen is for.
//
// Odoo shows an action's help text only on an EMPTY list, so the moment a
// shop has data nobody ever sees an explanation again, and a form is opened
// cold with no idea what it is or which of its forty fields matter.
//
// Text lives here rather than in the database because it is interface copy,
// not shop data: it should arrive with the module and be the same for every
// tenant. A model with no entry simply gets no banner, which is why this can
// never turn into filler on screens nobody asked about.
//
// `warn: true` renders amber instead of blue, reserved for screens where
// getting it wrong has consequences.
const FORM_INTROS = {
    // --- things a shop owner works with daily -------------------------
    "product.template": {
        text: "Everything you sell. Cost is what you pay for it, Sales Price is what the customer pays; the difference is your profit, shown on the Profit Analysis section below.",
    },
    "product.product": {
        text: "A specific version of a product, for example one size or colour. Prices and stock live here rather than on the parent product.",
    },
    "res.partner": {
        text: "One record for anyone you deal with. Tick Customer, Vendor or both; the tabs that appear change to match.",
    },
    "pos.order": {
        text: "A sale that has already gone through the till. It is kept as a record, so figures cannot be edited here; use a refund at the till to correct one.",
        warn: true,
    },
    "sale.order": {
        text: "A quotation is a price offered to a customer; it becomes an order once they accept. Nothing is taken out of stock until it is confirmed.",
    },
    "purchase.order": {
        text: "An order you place with a vendor. Stock only increases when the goods actually arrive and you receive them, not when the order is confirmed.",
    },
    "account.move": {
        text: "A bill in or out. It can be edited while it is a Draft; once posted it is part of your accounts and can only be corrected with a credit note.",
        warn: true,
    },
    "stock.picking": {
        text: "Goods moving in or out. Nothing changes in your stock figures until you validate it.",
    },
    "stock.quant": {
        text: "What the system believes is on your shelves. Type what you actually counted and apply it; the difference is posted as a correction.",
    },
    "stock.scrap": {
        text: "Stock you can no longer sell. Confirming removes it from your figures and files it under the reason you choose.",
        warn: true,
    },
    "product.uom": {
        text: "A pack size of a product, such as a 5 kg bag. It has its own barcode and price, while stock is still counted in the product's own unit.",
    },
    "pos.retail.expense": {
        text: "Money the shop spends that is not stock: rent, electricity, wages. These feed the expense totals on your dashboard.",
    },
    "pos.retail.ledger.adjustment": {
        text: "Corrects what a customer owes by posting a real accounting entry. Past entries are never rewritten, so a mistake is fixed by posting another adjustment the other way.",
        warn: true,
    },
    "pos.retail.access.role": {
        text: "A job role, built by ticking the permissions it should have. Assigning a user to the role gives them exactly those rights, and removing it takes them away immediately.",
    },
    "pos.config": {
        text: "Settings for one till. Changes take effect the next time that till is opened.",
    },
    "res.users": {
        text: "A login. What this person can see and do comes from the roles and permissions assigned to them, not from this screen alone.",
    },

    // --- advanced configuration a shop owner should rarely touch -------
    "stock.picking.type": {
        text: "Advanced setup that defines a kind of stock movement, such as Delivery or Receipt. Your shop already has the ones it needs; you only come here to add a new warehouse process. Sequence Prefix is simply the letters that start each reference number, for example WH/OUT.",
        warn: true,
    },
    "stock.location": {
        text: "Advanced setup: a place stock can sit. A single shop needs only the ones already set up.",
        warn: true,
    },
    "stock.warehouse": {
        text: "Advanced setup: a whole site holding stock. Most shops have exactly one and never change this.",
        warn: true,
    },
    "account.journal": {
        text: "Advanced accounting setup: a book your entries are filed in. Ask your accountant before changing anything here.",
        warn: true,
    },
};

patch(FormController.prototype, {
    get posRetailIntro() {
        return FORM_INTROS[this.props.resModel] || null;
    },
});

export { FORM_INTROS };
