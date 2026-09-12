/** @odoo-module **/

// Central registry mapping model names to the reports and phone fields
// available for PDF download and WhatsApp sharing.  Both the bulk-action
// toolbar on list views and the WhatsApp widget on form views read from
// this one object, so adding a report to a model is a single-line change.

import { Registry } from "@web/core/registry";

export const posRetailReportRegistry = new Registry();

posRetailReportRegistry.add("res.partner", {
    reports: [
        { name: "pos_retail.report_customer_ledger", label: "Customer Ledger" },
        { name: "pos_retail.report_khata_statement", label: "Khata Statement" },
        { name: "pos_retail.report_vendor_statement", label: "Vendor Statement" },
    ],
    phoneField: "mobile",
});

posRetailReportRegistry.add("sale.order", {
    reports: [
        { name: "sale.report_saleorder", label: "Quotation / Order" },
    ],
    phoneField: "partner_id.mobile",
});

posRetailReportRegistry.add("purchase.order", {
    reports: [
        { name: "purchase.report_purchaseorder", label: "Purchase Order" },
    ],
    phoneField: "partner_id.mobile",
});

posRetailReportRegistry.add("account.move", {
    reports: [
        { name: "account.report_invoice_with_payments", label: "Invoice" },
    ],
    phoneField: "partner_id.mobile",
});

posRetailReportRegistry.add("account.payment", {
    reports: [
        { name: "pos_retail.report_pos_retail_payment_receipt", label: "Payment Receipt" },
    ],
    phoneField: "partner_id.mobile",
});

posRetailReportRegistry.add("stock.picking", {
    reports: [
        { name: "stock.report_deliveryslip", label: "Delivery Slip" },
        { name: "pos_retail.report_goods_receipt_note", label: "Goods Receipt Note" },
    ],
    phoneField: "partner_id.mobile",
});

posRetailReportRegistry.add("pos.order", {
    reports: [
        { name: "pos_retail.report_pos_receipt_a4", label: "Receipt" },
    ],
    phoneField: "partner_id.mobile",
});

posRetailReportRegistry.add("pos.retail.discount.log", {
    reports: [
        { name: "pos_retail.report_discount_log", label: "Discount Audit" },
    ],
});
