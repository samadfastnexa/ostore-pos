/** @odoo-module **/

import { Component, useState } from "@odoo/owl";
import { Dialog } from "@web/core/dialog/dialog";
import { _t } from "@web/core/l10n/translation";
import { usePos } from "@point_of_sale/app/hooks/pos_hook";
import { useService } from "@web/core/utils/hooks";
import { posRetailRequestManagerPin } from "../utils/manager_pin";

export class ReturnNoReceiptPopup extends Component {
    static template = "pos_retail.ReturnNoReceiptPopup";
    static components = { Dialog };
    static props = { close: Function, getPayload: Function, order: { type: Object, optional: true } };

    setup() {
        this.parseFloat = parseFloat;
        this.pos = usePos();
        this.orm = useService("orm");
        this.notification = useService("notification");
        this.dialog = useService("dialog");

        const availableReasons = this.pos.models["pos.retail.return.reason"]?.getAll() || [];
        const defaultReasonId = availableReasons.length > 0 ? availableReasons[0].id : false;

        this.state = useState({
            returnMode: "no_receipt", // "no_receipt" or "linked"
            search: "",
            productId: false,
            qty: "1",
            price: "",
            condition: "resalable",
            reasonId: defaultReasonId,
            reasonNote: "",
            policyText: "",
            policyCode: this.pos.config.pos_retail_no_receipt_price_policy || "current_price",
            reference: "",
            linking: false,
            linkResult: null,
            lines: [],
        });
    }

    get returnReasons() {
        return this.pos.models["pos.retail.return.reason"]?.getAll() || [];
    }

    get products() {
        const all = this.pos.models["product.product"]
            .getAll()
            .filter((p) => p.available_in_pos);
        const word = this.state.search.trim();
        const list = word ? this.pos.getProductsBySearchWord(word, all) : all;
        return list.slice(0, 20);
    }

    get selectedProduct() {
        return this.state.productId
            ? this.pos.models["product.product"].get(this.state.productId)
            : false;
    }

    async selectProduct(product) {
        this.state.productId = product.id;
        this.state.linkResult = null;

        if (this.state.returnMode === "linked" && this.state.reference.trim()) {
            await this.lookupOriginal();
            return;
        }

        const policy = this.pos.config.pos_retail_no_receipt_price_policy || "current_price";
        this.state.policyCode = policy;

        if (policy === "cost") {
            this.state.price = String(product.standard_price || 0);
            this.state.policyText = _t("Policy: Product Cost");
        } else if (policy === "manager_price") {
            this.state.price = String(product.lst_price || 0);
            this.state.policyText = _t("Policy: Manager Price (Approval Mandatory)");
        } else if (policy === "lowest_price") {
            this.state.policyText = _t("Querying lowest sold price...");
            try {
                const res = await this.orm.call("pos.config", "get_no_receipt_product_price", [
                    this.pos.config.id,
                    product.id,
                ]);
                this.state.price = String(res.price || product.lst_price || 0);
                this.state.policyText = _t(
                    "Policy: Lowest Sold Price in %s Days",
                    this.pos.config.pos_retail_no_receipt_period_days || 30
                );
            } catch {
                this.state.price = String(product.lst_price || 0);
                this.state.policyText = _t("Policy: Current Price (Fallback)");
            }
        } else {
            this.state.price = String(product.lst_price || 0);
            this.state.policyText = _t("Policy: Current Selling Price");
        }
    }

    clearProduct() {
        this.state.productId = false;
        this.state.linkResult = null;
        this.state.policyText = "";
    }

    get partner() {
        return this.props.order?.getPartner();
    }

    async pickCustomer() {
        await this.pos.selectPartner(this.props.order);
    }

    setReturnMode(mode) {
        this.state.returnMode = mode;
        if (this.selectedProduct) {
            this.selectProduct(this.selectedProduct);
        }
    }

    async lookupOriginal() {
        const reference = this.state.reference.trim();
        if (!reference || !this.selectedProduct) {
            return;
        }
        this.state.linking = true;
        try {
            const result = await this.orm.call(
                "pos.order", "pos_retail_find_return_source",
                [reference, this.selectedProduct.id, this.pos.config.id]
            );
            this.state.linkResult = result;
            if (result.found) {
                this.state.price = String(result.price_unit);
                this.state.policyText = _t("Original Sale Price (Linked: %s)", result.order_name);
                if (parseFloat(this.state.qty) > result.returnable_qty) {
                    this.state.qty = String(result.returnable_qty);
                }
            } else {
                this.state.policyText = "";
            }
        } finally {
            this.state.linking = false;
        }
    }

    get maxQty() {
        if (!this.state.linkResult?.found) {
            return Infinity;
        }
        const reserved = this.state.lines
            .filter((line) => line.originalOrderLineId === this.state.linkResult.order_line_id)
            .reduce((total, line) => total + line.qty, 0);
        return Math.max(0, this.state.linkResult.returnable_qty - reserved);
    }

    get isOverMaxQty() {
        const qty = parseFloat(this.state.qty || 0);
        return qty > this.maxQty;
    }

    clearLink() {
        this.state.reference = "";
        this.state.linkResult = null;
        if (this.selectedProduct) {
            this.selectProduct(this.selectedProduct);
        }
    }

    get canAddLine() {
        const reasonObj = this.returnReasons.find((r) => r.id === parseInt(this.state.reasonId, 10));
        const isOther = reasonObj && reasonObj.name.toLowerCase().includes("other");
        if (isOther && !this.state.reasonNote.trim()) {
            return false;
        }
        return Boolean(
            this.selectedProduct &&
                parseFloat(this.state.qty) > 0 &&
                parseFloat(this.state.qty) <= this.maxQty &&
                parseFloat(this.state.price) >= 0
        );
    }

    get canConfirm() {
        return this.state.lines.length > 0;
    }

    get cartTotal() {
        return this.state.lines.reduce((sum, line) => sum + (line.qty * line.price), 0);
    }

    addLine() {
        if (!this.canAddLine) {
            return;
        }
        const link = this.state.linkResult?.found ? this.state.linkResult : false;
        const selectedReason = this.returnReasons.find((r) => r.id === parseInt(this.state.reasonId, 10));

        const line = {
            product: this.selectedProduct,
            qty: parseFloat(this.state.qty),
            price: parseFloat(this.state.price),
            condition: this.state.condition,
            reasonId: this.state.reasonId ? parseInt(this.state.reasonId, 10) : false,
            reasonName: selectedReason ? selectedReason.name : "",
            reasonNote: this.state.reasonNote.trim(),
            policy: this.state.policyCode,
            originalOrderId: link ? link.order_id : false,
            originalOrderLineId: link ? link.order_line_id : false,
            unlinked: !link,
        };

        const existing = this.state.lines.find((candidate) =>
            candidate.product.id === line.product.id
            && candidate.price === line.price
            && candidate.condition === line.condition
            && candidate.originalOrderLineId === line.originalOrderLineId
        );
        if (existing) {
            existing.qty += line.qty;
        } else {
            this.state.lines.push(line);
        }

        this.clearProduct();
        this.state.search = "";
        this.state.qty = "1";
        this.state.price = "";
        this.state.reference = "";
        this.state.reasonNote = "";
    }

    removeLine(index) {
        this.state.lines.splice(index, 1);
    }

    async confirm() {
        if (!this.canConfirm) {
            return;
        }

        const totalAmount = this.cartTotal;
        const config = this.pos.config;
        const approvalMode = config.pos_retail_no_receipt_approval_mode || "amount";
        const approvalLimit = config.pos_retail_no_receipt_approval_limit || 3000;
        const hasManagerPolicy = this.state.lines.some((l) => l.policy === "manager_price" && l.unlinked);

        let manager = null;
        if (
            approvalMode === "always" ||
            hasManagerPolicy ||
            (approvalMode === "amount" && totalAmount > approvalLimit)
        ) {
            manager = await posRetailRequestManagerPin(this.pos, this.dialog, this.notification, {
                noManagerMessage: _t(
                    "Manager approval is required for this refund (Total exceeds limit or policy requires manager authorization)."
                ),
            });
            if (!manager) {
                return;
            }
        }

        this.props.getPayload({
            lines: this.state.lines,
            unlinked: this.state.lines.some((line) => line.unlinked),
            manager: manager,
        });
        this.props.close();
    }

    get linkStatusMessage() {
        const r = this.state.linkResult;
        if (!r || r.found) {
            return "";
        }
        if (r.reason === "no_matching_product") {
            return _t("Order %s does not have this product on it. Continuing without a link.", r.order_name);
        }
        if (r.reason === "outside_return_policy") {
            return _t("%s is outside the configured return window. A manager-approved unlinked return is still possible.", r.order_name);
        }
        return _t("No order found for that reference. Continuing without a link.");
    }
}
