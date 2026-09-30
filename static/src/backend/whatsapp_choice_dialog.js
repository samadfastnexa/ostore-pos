/** @odoo-module **/

import { Component } from "@odoo/owl";
import { AlertDialog } from "@web/core/confirmation_dialog/confirmation_dialog";
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
 * Ask Web or App (every time, nothing remembered), then send the document.
 *
 * The PDF goes on its own, never with the message: the shop wants the
 * customer to receive the document, not a wall of text with a link. WhatsApp's
 * own links (wa.me, web.whatsapp.com/send, whatsapp://send) carry TEXT only --
 * no website can attach a file through them -- so:
 *
 *   App  -> the operating system's share sheet with the PDF file alone: pick
 *           WhatsApp, pick the person, the PDF is attached. Chrome/Edge on
 *           Windows (with WhatsApp Desktop installed), Android, iPhone and a
 *           Chromebook with the WhatsApp app all do this. Where the browser
 *           cannot share files, the chat opens empty and the PDF is
 *           downloaded to attach.
 *   Web  -> WhatsApp Web can never receive a file from another tab (Chromebook
 *           is the usual case), so the person's chat opens EMPTY and the PDF
 *           is downloaded: drag it from the downloads icon into the chat, or
 *           paperclip > Document.
 *
 * The message is only sent when there is no PDF at all (it failed to render,
 * or the caller shares text), so the customer is never left with nothing.
 *
 * `text` is the fallback message; `phone` international digits, or "" to let
 * the user pick the chat. Returns "file" when the PDF itself was handed to
 * WhatsApp, "download" when the chat was opened and the PDF downloaded to
 * attach, "text" when only the message went, false when the user backed out.
 */
export async function openWhatsAppChoice(dialogService, phone = "", { blob = null, filename = "document.pdf", text = "" } = {}) {
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

    const query = (params) => Object.entries(params)
        .filter(([, value]) => value)
        .map(([key, value]) => `${key}=${encodeURIComponent(value)}`)
        .join("&");

    // With a PDF the chat opens empty (the file is the message); without one
    // the text is all there is, so it goes instead of nothing.
    const chatParams = () => query(blob ? { phone } : { phone, text });

    const explainAttach = (why) => {
        if (typeof dialogService?.add !== "function") {
            return;
        }
        dialogService.add(AlertDialog, {
            title: _t("Attach the PDF in WhatsApp"),
            body: _t(
                "%(why)s The PDF \"%(file)s\" has been downloaded. In the chat, press the paperclip (+), choose Document, and pick it from Downloads.",
                { why, file: filename }
            ),
        });
    };

    // 3. Execute chosen target without storing preference
    if (chosen === "web") {
        // The steps are on the button itself: this tab loses focus to the
        // WhatsApp tab, so a dialog here would only be seen afterwards.
        downloadBlob();
        // No number (a walk-in) and no text: /send with nothing is an error
        // page, the home screen lets the cashier pick the chat.
        const params = chatParams();
        window.open(params ? `https://web.whatsapp.com/send?${params}` : "https://web.whatsapp.com/",
            "_blank", "noopener,noreferrer");
        return blob ? "download" : "text";
    }

    // App: any platform whose browser can share files -- not just phones.
    // Chrome and Edge on Windows hand the PDF to the Windows share sheet,
    // where WhatsApp Desktop is listed; ChromeOS to its own, where the
    // WhatsApp app from the Play Store is.
    if (blob && typeof navigator !== "undefined" && typeof navigator.share === "function") {
        const file = new File([blob], filename, { type: "application/pdf" });
        if (navigator.canShare?.({ files: [file] })) {
            try {
                // The file alone: handed a title or text as well, WhatsApp
                // keeps the text and drops the file.
                await navigator.share({ files: [file] });
                return "file";
            } catch (err) {
                if (err && err.name === "AbortError") {
                    return false; // the share sheet was closed without sending
                }
                console.warn("pos_retail: file share failed, opening the chat instead", err);
            }
        }
    }
    downloadBlob();
    const params = chatParams();
    const a = document.createElement("a");
    a.href = `whatsapp://send${params ? "?" + params : ""}`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    if (!blob) {
        return "text";
    }
    explainAttach(_t("This browser cannot hand a file to WhatsApp, so the chat was opened for you."));
    return "download";
}
