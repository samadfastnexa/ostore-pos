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
 * Handles automatic PDF download and launches either WhatsApp Web or WhatsApp App.
 */
export async function openWhatsAppChoice(dialogService, phone = "", { blob = null, filename = "document.pdf" } = {}) {
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

    // Helper: download blob to computer
    const downloadBlob = () => {
        if (!blob) return;
        try {
            const blobUrl = URL.createObjectURL(blob);
            const a = document.createElement("a");
            a.href = blobUrl;
            a.download = filename;
            document.body.appendChild(a);
            a.click();
            document.body.removeChild(a);
            setTimeout(() => URL.revokeObjectURL(blobUrl), 2000);
        } catch (e) {
            console.warn("pos_retail: PDF download error", e);
        }
    };

    // 3. Execute chosen target without storing preference
    if (chosen === "web") {
        downloadBlob();
        const url = phone
            ? `https://web.whatsapp.com/send?phone=${encodeURIComponent(phone)}`
            : `https://web.whatsapp.com/`;
        window.open(url, "_blank", "noopener,noreferrer");
    } else if (chosen === "app") {
        const isMobile = typeof navigator !== "undefined" && /Android|iPhone|iPad|iPod/i.test(navigator.userAgent);
        let sharedDirectly = false;

        // On mobile, if native share is supported, share the PDF file directly into WhatsApp app
        if (isMobile && blob && typeof navigator !== "undefined" && typeof navigator.share === "function") {
            try {
                const file = new File([blob], filename, { type: "application/pdf" });
                if (navigator.canShare?.({ files: [file] })) {
                    await navigator.share({
                        files: [file],
                        title: filename,
                    });
                    sharedDirectly = true;
                }
            } catch (err) {
                if (err && err.name === "AbortError") {
                    return true;
                }
            }
        }

        if (!sharedDirectly) {
            downloadBlob();
            const appUrl = phone
                ? `whatsapp://send?phone=${encodeURIComponent(phone)}`
                : `whatsapp://`;
            const a = document.createElement("a");
            a.href = appUrl;
            document.body.appendChild(a);
            a.click();
            document.body.removeChild(a);
        }
    }
    return true;
}
