/** @odoo-module **/

import { Component } from "@odoo/owl";
import { Dialog } from "@web/core/dialog/dialog";
import { _t } from "@web/core/l10n/translation";

/**
 * WhatsApp Choice Dialog:
 * Prompts user every single time to choose between "WhatsApp Web" and "WhatsApp App".
 * Explicitly does not remember or persist the selection anywhere in localStorage or cookies.
 */
export class WhatsAppChoiceDialog extends Component {
    static template = "pos_retail.WhatsAppChoiceDialog";
    static components = { Dialog };
    static props = {
        phone: { type: String, optional: true },
        onSelect: { type: Function },
        close: { type: Function },
    };

    selectWeb() {
        this.props.onSelect("web");
        this.props.close();
    }

    selectApp() {
        this.props.onSelect("app");
        this.props.close();
    }
}

/**
 * Helper function to clear any saved preferences and prompt choice modal every time.
 */
export async function openWhatsAppChoice(dialogService, phone = "") {
    // 1. Actively clear any past saved preference from all storage
    try {
        localStorage.removeItem("pos_retail_whatsapp_choice");
        localStorage.removeItem("pos_retail_whatsapp_mode");
        localStorage.removeItem("whatsapp_target");
        localStorage.removeItem("pos_retail_whatsapp_pref");
        sessionStorage.removeItem("pos_retail_whatsapp_choice");
        sessionStorage.removeItem("pos_retail_whatsapp_mode");
        sessionStorage.removeItem("whatsapp_target");
        sessionStorage.removeItem("pos_retail_whatsapp_pref");
    } catch (_) {}

    // 2. Prompt every single time via Owl Dialog
    let chosen = null;
    if (typeof dialogService?.add === "function") {
        await new Promise((resolve) => {
            dialogService.add(WhatsAppChoiceDialog, {
                phone,
                onSelect: (val) => {
                    chosen = val;
                    resolve(val);
                },
                close: () => resolve(null),
            });
        });
    }

    if (!chosen) {
        return false; // User dismissed or cancelled
    }

    // 3. Open chosen target without storing preference
    if (chosen === "web") {
        const url = phone
            ? `https://web.whatsapp.com/send?phone=${encodeURIComponent(phone)}`
            : `https://web.whatsapp.com/`;
        window.open(url, "_blank", "noopener,noreferrer");
    } else if (chosen === "app") {
        const url = phone
            ? `whatsapp://send?phone=${encodeURIComponent(phone)}`
            : `whatsapp://`;
        const a = document.createElement("a");
        a.href = url;
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
    }
    return true;
}
