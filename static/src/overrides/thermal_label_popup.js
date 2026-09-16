/** @odoo-module **/

import { Component, useState } from "@odoo/owl";
import { Dialog } from "@web/core/dialog/dialog";
import { _t } from "@web/core/l10n/translation";
import { usePos } from "@point_of_sale/app/hooks/pos_hook";

export class ThermalLabelPopup extends Component {
    static template = "pos_retail.ThermalLabelPopup";
    static components = { Dialog };
    static props = {
        close: Function,
        product: Object,
    };

    setup() {
        this.pos = usePos();
        
        // Find default preset from config or preset list
        const defaultPresetId = this.findDefaultPresetId();

        this.state = useState({
            presetId: defaultPresetId,
            quantity: 1,
            printing: false,
        });
    }

    get product() {
        return this.props.product;
    }

    get presets() {
        try {
            const model = this.pos.models?.["pos.retail.thermal.label.preset"] || this.pos.data?.models?.["pos.retail.thermal.label.preset"];
            if (model && model.getAll) {
                return model.getAll();
            }
        } catch (_) {}
        return [];
    }

    findDefaultPresetId() {
        const configPresetId = this.pos.config.thermal_label_preset_id?.id || this.pos.config.thermal_label_preset_id;
        if (configPresetId) {
            return configPresetId;
        }
        const presets = this.presets;
        const def = presets.find((p) => p.is_default);
        if (def) {
            return def.id;
        }
        return presets.length > 0 ? presets[0].id : 0;
    }

    get selectedPreset() {
        const id = parseInt(this.state.presetId, 10);
        return this.presets.find((p) => p.id === id) || null;
    }

    setPreset(ev) {
        this.state.presetId = parseInt(ev.target.value, 10);
    }

    setQty(qty) {
        this.state.quantity = Math.max(1, parseInt(qty, 10) || 1);
    }

    incrementQty(delta) {
        this.state.quantity = Math.max(1, this.state.quantity + delta);
    }

    printLabels(isSingle = false) {
        const productId = this.product.id;
        const presetId = this.state.presetId || "";
        const qty = isSingle ? 1 : this.state.quantity;

        let url = `/pos_retail/print_thermal_labels?product_id=${productId}&qty=${qty}`;
        if (presetId) {
            url += `&preset_id=${presetId}`;
        }
        if (isSingle) {
            url += `&single=1`;
        }

        // Open in printable popup window
        const win = window.open(
            url,
            "ThermalLabelPrint",
            "width=600,height=700,menubar=no,toolbar=no,location=no,status=no"
        );
        if (win) {
            win.focus();
        }

        if (this.pos.notification) {
            this.pos.notification.add(
                _t("%(qty)s label(s) sent to thermal printer.", { qty: qty }),
                { type: "success" }
            );
        }

        this.props.close();
    }

    printTestLabel() {
        this.printLabels(true);
    }
}
