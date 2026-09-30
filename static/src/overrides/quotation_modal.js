/** @odoo-module **/

import { Component, onWillStart, useState } from "@odoo/owl";
import { Dialog } from "@web/core/dialog/dialog";
import { _t } from "@web/core/l10n/translation";
import { usePos } from "@point_of_sale/app/hooks/pos_hook";
import { useService } from "@web/core/utils/hooks";
import { openWhatsAppChoice } from "../backend/whatsapp_choice_dialog";
import { rpc } from "@web/core/network/rpc";

/**
 * Share a sales quotation over WhatsApp with its official PDF attachment,
 * tokenized public download link, and formatted breakdown message.
 */
export async function shareQuotationOnWhatsApp({ pos, dialog, notification, quote, lines = null }) {
    if (!quote?.id) return false;

    // 1. Fetch quotation lines if not provided
    let quoteLines = lines;
    let quoteData = quote;
    if (!quoteLines) {
        try {
            quoteData = await pos.data.call("sale.order", "pos_retail_get_quotation_lines", [quote.id]);
            quoteLines = quoteData.lines || [];
        } catch (e) {
            console.warn("pos_retail: Could not fetch quotation lines for WhatsApp", e);
            quoteLines = [];
        }
    }

    // 2. Resolve customer phone number & normalize with dial code
    const rawPhone = quoteData.partner_phone || quoteData.partner_mobile || quote.partner_phone || quote.partner_mobile || "";
    let digits = String(rawPhone).replace(/\D/g, "");
    if (digits.startsWith("00")) {
        digits = digits.slice(2);
    }
    const phoneCode = String(pos.company?.country_id?.phone_code || "92").replace(/\D/g, "");
    if (digits.startsWith("0")) {
        digits = phoneCode ? phoneCode + digits.slice(1) : digits.slice(1);
    } else if (phoneCode && digits.length <= 10 && digits.length > 0 && !digits.startsWith(phoneCode)) {
        digits = phoneCode + digits;
    }

    // 3. Fetch PDF Blob and public tokenized download URL concurrently
    const filename = `Quotation_${(quote.name || "quote").replace(/[\\/]/g, "-")}.pdf`;
    let pdfBlob = null;
    let pdfUrl = "";

    try {
        const [pdfRes, docShare] = await Promise.all([
            fetch(`/report/pdf/sale.report_saleorder/${quote.id}`, { credentials: "same-origin" }),
            rpc("/pos_retail/portal/get_doc_share_info", {
                model_name: "sale.order",
                res_id: quote.id,
                report: "sale.report_saleorder",
            }).catch(() => null),
        ]);

        if (pdfRes && pdfRes.ok) {
            pdfBlob = await pdfRes.blob();
        }
        if (docShare?.pdf_url) {
            pdfUrl = docShare.pdf_url;
        }
    } catch (err) {
        console.warn("pos_retail: Could not prepare PDF for quotation WhatsApp share", err);
    }

    // 4. Build formatted WhatsApp message text
    const fmt = (v) => pos.env.utils.formatCurrency(v || 0);
    const shopName = pos.company?.name || "";
    const msg = [];
    if (shopName) {
        msg.push(`*${shopName}*`);
    }
    msg.push(`*QUOTATION - ${quote.name}*`);
    if (quote.date || quoteData.date) {
        msg.push(`Date: ${quote.date || quoteData.date}`);
    }
    if (quote.validity_date || quoteData.validity_date) {
        msg.push(`Valid Until: ${quote.validity_date || quoteData.validity_date}`);
    }
    if (quote.partner_name || quoteData.partner_name) {
        msg.push(`Customer: *${quote.partner_name || quoteData.partner_name}*`);
    }
    msg.push(`--------------------------------`);
    if (quoteLines && quoteLines.length) {
        for (const item of quoteLines) {
            const qtyStr = `${item.qty} ${item.uom || "Units"}`.trim();
            const priceStr = fmt(item.price_unit);
            const subtotal = item.price_subtotal ?? (item.qty * item.price_unit * (1 - (item.discount || 0) / 100));
            const subtotalStr = fmt(subtotal);
            msg.push(`• *${item.product_name || item.display_name}*`);
            msg.push(`  ${qtyStr} x ${priceStr}${item.discount ? ` (-${item.discount}%)` : ""} = ${subtotalStr}`);
        }
        msg.push(`--------------------------------`);
    }
    msg.push(`*TOTAL AMOUNT: ${fmt(quote.amount_total || quoteData.amount_total)}*`);
    if (pdfUrl) {
        msg.push(``);
        msg.push(`📄 *Download Official PDF Quotation:*`);
        msg.push(pdfUrl);
    }
    msg.push(``);
    msg.push(`Thank you for choosing ${shopName || "us"}!`);
    const whatsappText = msg.join("\n");

    // 5. Open unified WhatsApp Choice Dialog (Web vs App)
    const shared = await openWhatsAppChoice(dialog, digits, {
        blob: pdfBlob,
        filename,
        text: whatsappText,
    });

    if (shared === "file") {
        notification.add(_t("Quotation PDF processed for WhatsApp sharing."), { type: "info" });
    }
    return true;
}

export class PosRetailQuotationModal extends Component {
    static template = "pos_retail.QuotationModal";
    static components = { Dialog };
    static props = {
        close: Function,
    };

    setup() {
        this.pos = usePos();
        this.dialog = useService("dialog");
        this.notification = useService("notification");
        this.action = useService("action");

        const currentPartner = this.pos.getOrder()?.getPartner() || null;

        this.state = useState({
            loading: true,
            searchQuery: "",
            filter: "all",
            onlyThisCustomer: false,
            currentPartner: currentPartner,
            quotations: [],
            isLoadingLines: false,
            errorMessage: "",
            sharingQuoteId: null,

            // INLINE QUOTATION EDITOR STATE
            editingQuote: null,
            editLines: [],
            editPartnerId: null,
            editPartnerName: "",
            editPartnerPhone: "",
            editValidityDate: "",
            editNote: "",
            editSaving: false,
            isDirty: false,

            // Product search inside editor
            productSearchQuery: "",
            productSearchResults: [],
            searchingProducts: false,
        });

        this._searchTimeout = null;
        this._productSearchTimeout = null;

        onWillStart(async () => {
            await this.fetchQuotations();
        });
    }

    async fetchQuotations() {
        this.state.loading = true;
        this.state.errorMessage = "";
        try {
            const partnerId =
                this.state.onlyThisCustomer && this.state.currentPartner
                    ? this.state.currentPartner.id
                    : false;
            const res = await this.pos.data.call(
                "sale.order",
                "pos_retail_search_quotations",
                [],
                {
                    partner_id: partnerId,
                    query: this.state.searchQuery || "",
                    limit: 50,
                }
            );
            this.state.quotations = res || [];
        } catch (err) {
            this.state.errorMessage =
                err?.data?.message || err?.message || _t("Failed to load quotations.");
        } finally {
            this.state.loading = false;
        }
    }

    onSearchInput(ev) {
        this.state.searchQuery = ev.target.value;
        clearTimeout(this._searchTimeout);
        this._searchTimeout = setTimeout(() => {
            this.fetchQuotations();
        }, 300);
    }

    clearSearch() {
        this.state.searchQuery = "";
        this.fetchQuotations();
    }

    toggleCustomerFilter() {
        this.state.onlyThisCustomer = !this.state.onlyThisCustomer;
        this.fetchQuotations();
    }

    setFilter(filterName) {
        this.state.filter = filterName;
    }

    get filteredQuotations() {
        let list = this.state.quotations;

        if (this.state.filter !== "all") {
            list = list.filter((q) => q.state === this.state.filter);
        }

        const term = (this.state.searchQuery || "").trim().toLowerCase();
        if (term) {
            list = list.filter(
                (q) =>
                    (q.name || "").toLowerCase().includes(term) ||
                    (q.partner_name || "").toLowerCase().includes(term) ||
                    (q.partner_phone || "").includes(term)
            );
        }

        return list;
    }

    formatMoney(val) {
        return this.pos.env.utils.formatCurrency(val || 0);
    }

    // ==========================================
    // QUOTATION ACTIONS: LOAD, PRINT, DUPLICATE, WHATSAPP
    // ==========================================

    async loadQuoteIntoCart(quote) {
        this.state.isLoadingLines = true;
        try {
            const res = await this.pos.data.call(
                "sale.order",
                "pos_retail_get_quotation_lines",
                [quote.id]
            );

            if (!res || !res.lines || !res.lines.length) {
                this.notification.add(_t("This quotation has no items."), { type: "warning" });
                return;
            }

            const currentOrder = this.pos.getOrder();

            if (res.partner_id) {
                const partner = this.pos.models["res.partner"].get(res.partner_id);
                if (partner) {
                    currentOrder.setPartner(partner);
                }
            }

            let addedCount = 0;
            for (const item of res.lines) {
                const prod = this.pos.models["product.product"].get(item.product_id);
                if (prod) {
                    await this.pos.addLineToCurrentOrder(
                        {
                            product_id: prod,
                            product_tmpl_id: prod.product_tmpl_id,
                            qty: item.qty,
                            price_unit: item.price_unit,
                            discount: item.discount || 0,
                        },
                        {}
                    );
                    addedCount += 1;
                }
            }

            this.notification.add(
                _t("Loaded %(count)s item(s) from %(quote)s into the order.", {
                    count: addedCount,
                    quote: quote.name,
                }),
                { type: "success" }
            );

            this.props.close();
        } catch (err) {
            this.state.errorMessage =
                err?.data?.message || err?.message || _t("Could not load quotation lines.");
        } finally {
            this.state.isLoadingLines = false;
        }
    }

    printQuotationPdf(quote) {
        if (!quote.id) return;
        const url = `/pos_retail/print_report?report=sale.action_report_saleorder&id=${quote.id}`;
        let iframe = document.getElementById("pos_retail_direct_print_frame");
        if (!iframe) {
            iframe = document.createElement("iframe");
            iframe.id = "pos_retail_direct_print_frame";
            iframe.style.position = "fixed";
            iframe.style.right = "0";
            iframe.style.bottom = "0";
            iframe.style.width = "0";
            iframe.style.height = "0";
            iframe.style.border = "0";
            document.body.appendChild(iframe);
        }
        iframe.src = url;
        this.notification.add(_t("Sending %(quote)s to printer...", { quote: quote.name }), { type: "info" });
    }

    async duplicateQuotation(quote) {
        try {
            const copy = await this.pos.data.call(
                "sale.order",
                "pos_retail_duplicate_quotation",
                [quote.id]
            );
            this.notification.add(
                _t("Duplicated %(old)s to fresh draft %(new)s.", {
                    old: quote.name,
                    new: copy.name,
                }),
                { type: "success" }
            );
            await this.fetchQuotations();
        } catch (err) {
            this.notification.add(_t("Could not duplicate quotation."), { type: "danger" });
        }
    }

    async shareQuotationWhatsApp(quote) {
        if (this.state.sharingQuoteId) return;
        this.state.sharingQuoteId = quote.id;
        try {
            await shareQuotationOnWhatsApp({
                pos: this.pos,
                dialog: this.dialog,
                notification: this.notification,
                quote: quote,
            });
        } catch (err) {
            console.error("WhatsApp share failed:", err);
            this.notification.add(
                err?.message || _t("Could not share quotation on WhatsApp."),
                { type: "danger" }
            );
        } finally {
            this.state.sharingQuoteId = null;
        }
    }

    // ==========================================
    // INLINE QUOTATION EDITOR
    // ==========================================

    async openEditor(quote) {
        this.state.loading = true;
        this.state.errorMessage = "";
        try {
            const details = await this.pos.data.call(
                "sale.order",
                "pos_retail_get_quotation_lines",
                [quote.id]
            );

            this.state.editingQuote = quote;
            this.state.editLines = (details.lines || []).map((l) => ({
                id: l.id,
                product_id: l.product_id,
                product_name: l.product_name,
                brand_name: l.brand_name || "",
                barcode: l.barcode || "",
                default_code: l.default_code || "",
                uom: l.uom || "Units",
                qty: parseFloat(l.qty) || 1,
                price_unit: parseFloat(l.price_unit) || 0,
                discount: parseFloat(l.discount) || 0,
            }));
            this.state.editPartnerId = details.partner_id || quote.partner_id || false;
            this.state.editPartnerName = details.partner_name || quote.partner_name || "";
            this.state.editPartnerPhone = details.partner_phone || quote.partner_phone || "";
            this.state.editValidityDate = details.validity_date || quote.validity_date || "";
            this.state.editNote = details.note || quote.note || "";
            this.state.isDirty = false;
            this.state.productSearchQuery = "";
            this.state.productSearchResults = [];
        } catch (err) {
            this.state.errorMessage =
                err?.data?.message || err?.message || _t("Could not load quotation details for editing.");
        } finally {
            this.state.loading = false;
        }
    }

    closeEditor() {
        this.state.editingQuote = null;
        this.state.editLines = [];
        this.state.productSearchQuery = "";
        this.state.productSearchResults = [];
        this.fetchQuotations();
    }

    get computedEditTotal() {
        return (this.state.editLines || []).reduce((acc, l) => {
            const qty = parseFloat(l.qty) || 0;
            const price = parseFloat(l.price_unit) || 0;
            const disc = parseFloat(l.discount) || 0;
            return acc + qty * price * (1 - disc / 100);
        }, 0);
    }

    updateLineQty(line, delta) {
        const current = parseFloat(line.qty) || 0;
        const next = Math.max(1, current + delta);
        line.qty = next;
        this.state.isDirty = true;
    }

    onLineQtyChange(line, ev) {
        const val = parseFloat(ev.target.value);
        line.qty = isNaN(val) || val <= 0 ? 1 : val;
        this.state.isDirty = true;
    }

    onLinePriceChange(line, ev) {
        const val = parseFloat(ev.target.value);
        line.price_unit = isNaN(val) || val < 0 ? 0 : val;
        this.state.isDirty = true;
    }

    onLineDiscountChange(line, ev) {
        const val = parseFloat(ev.target.value);
        line.discount = isNaN(val) || val < 0 ? 0 : Math.min(100, val);
        this.state.isDirty = true;
    }

    removeLine(index) {
        this.state.editLines.splice(index, 1);
        this.state.isDirty = true;
    }

    async changeEditCustomer() {
        const partner = await this.pos.selectPartner();
        if (partner) {
            this.state.editPartnerId = partner.id;
            this.state.editPartnerName = partner.name;
            this.state.editPartnerPhone = partner.phone || partner.mobile || "";
            this.state.isDirty = true;
        }
    }

    onProductSearchInput(ev) {
        const q = ev.target.value;
        this.state.productSearchQuery = q;
        clearTimeout(this._productSearchTimeout);
        if (!q.trim()) {
            this.state.productSearchResults = [];
            return;
        }
        this._productSearchTimeout = setTimeout(async () => {
            this.state.searchingProducts = true;
            try {
                const res = await this.pos.data.call(
                    "pos.session",
                    "pos_retail_search_stock",
                    [this.pos.config.id, q, 10]
                );
                this.state.productSearchResults = res?.products || [];
            } catch (err) {
                console.warn("Product search error:", err);
            } finally {
                this.state.searchingProducts = false;
            }
        }, 250);
    }

    addProductToEditQuote(prod) {
        const existing = this.state.editLines.find((l) => l.product_id === prod.id);
        if (existing) {
            existing.qty = (parseFloat(existing.qty) || 0) + 1;
        } else {
            this.state.editLines.push({
                product_id: prod.id,
                product_name: prod.name,
                brand_name: prod.brand_name || "",
                barcode: prod.barcode || "",
                default_code: prod.default_code || "",
                uom: prod.uom || "Units",
                qty: 1,
                price_unit: prod.list_price || 0,
                discount: 0,
            });
        }
        this.state.isDirty = true;
        this.state.productSearchQuery = "";
        this.state.productSearchResults = [];
    }

    async saveQuotationChanges() {
        if (!this.state.editLines.length) {
            this.notification.add(_t("Quotation must have at least one product."), { type: "warning" });
            return false;
        }

        this.state.editSaving = true;
        try {
            const payload = {
                partner_id: this.state.editPartnerId,
                validity_date: this.state.editValidityDate || false,
                note: this.state.editNote || false,
                lines: this.state.editLines.map((l) => ({
                    product_id: l.product_id,
                    qty: parseFloat(l.qty) || 1,
                    price_unit: parseFloat(l.price_unit) || 0,
                    discount: parseFloat(l.discount) || 0,
                })),
            };

            const updated = await this.pos.data.call(
                "sale.order",
                "pos_retail_update_quotation",
                [this.state.editingQuote.id, payload]
            );

            this.state.editingQuote = updated;
            this.state.isDirty = false;

            this.notification.add(
                _t("Quotation %(name)s updated successfully!", { name: updated.name }),
                { type: "success" }
            );
            return true;
        } catch (err) {
            this.notification.add(
                err?.data?.message || err?.message || _t("Failed to update quotation."),
                { type: "danger" }
            );
            return false;
        } finally {
            this.state.editSaving = false;
        }
    }

    async shareEditorWhatsApp() {
        if (this.state.isDirty) {
            const saved = await this.saveQuotationChanges();
            if (!saved) return;
        }
        await this.shareQuotationWhatsApp(this.state.editingQuote);
    }

    /**
     * Edit in POS Register Cart:
     * Transfers quotation lines into the active POS cart and sets edit mode,
     * so cashier can use barcode scanner and full POS product grid.
     */
    async editInPosCart() {
        const order = this.pos.getOrder();
        if (order.getOrderlines().length > 0) {
            order.removeOrderline(order.getOrderlines());
        }

        // Set customer
        if (this.state.editPartnerId) {
            const partner = this.pos.models["res.partner"].get(this.state.editPartnerId);
            if (partner) {
                order.setPartner(partner);
            }
        }

        // Add lines
        for (const item of this.state.editLines) {
            const prod = this.pos.models["product.product"].get(item.product_id);
            if (prod) {
                await this.pos.addLineToCurrentOrder(
                    {
                        product_id: prod,
                        product_tmpl_id: prod.product_tmpl_id,
                        qty: item.qty,
                        price_unit: item.price_unit,
                        discount: item.discount || 0,
                    },
                    {}
                );
            }
        }

        // Mark order with active quote editing ID and Name
        order.pos_retail_editing_quote_id = this.state.editingQuote.id;
        order.pos_retail_editing_quote_name = this.state.editingQuote.name;

        this.notification.add(
            _t("Now editing %(quote)s in POS register. Use 'Make Quotation' to save updates.", {
                quote: this.state.editingQuote.name,
            }),
            { type: "info" }
        );

        this.props.close();
    }
}
