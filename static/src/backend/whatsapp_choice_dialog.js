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
 * WhatsApp's own links (wa.me, web.whatsapp.com/send, whatsapp://send) carry
 * TEXT only -- no website can attach a file through them. So:
 *
 *   App  -> the operating system's share sheet with the real PDF file: pick
 *           WhatsApp, pick the person, the PDF is attached. Chrome/Edge on
 *           Windows (with WhatsApp Desktop installed), Android and iPhone all
 *           do this. Where the browser cannot share files (Firefox), falls
 *           back to opening the chat in the app with the message.
 *   Web  -> WhatsApp Web can never receive a file from another tab, so it
 *           opens the person's chat with the message already typed -- the
 *           callers put a download link to the PDF in it -- and downloads the
 *           PDF as well, for dragging into the chat if preferred.
 *
 * Whenever only the message could go out, the cashier is told so and shown
 * how to attach the downloaded PDF, instead of the chat quietly receiving
 * text and nobody noticing the statement never arrived.
 *
 * `text` is the message; `phone` international digits, or "" to let the user
 * pick the chat. Returns "file" when the PDF itself was handed to WhatsApp,
 * "text" when only the message was, false when the user backed out.
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

    // Only the message went out: say so, and how to add the PDF by hand.
    const explainTextOnly = (why) => {
        if (!blob || typeof dialogService?.add !== "function") {
            return;
        }
        dialogService.add(AlertDialog, {
            title: _t("Attach the PDF in WhatsApp"),
            body: _t(
                "%(why)s The PDF \"%(file)s\" has been downloaded to this computer. In the chat, press the paperclip (+), choose Document, and pick it from Downloads.",
                { why, file: filename }
            ),
        });
    };

    // 3. Execute chosen target without storing preference
    if (chosen === "web") {
        downloadBlob();
        const params = query({ phone, text });
        window.open(`https://web.whatsapp.com/send${params ? "?" + params : ""}`, "_blank", "noopener,noreferrer");
        explainTextOnly(_t("WhatsApp Web only accepts a message from a link, never a file."));
        return "text";
    }

    // App: any platform whose browser can share files -- not just phones.
    // Chrome and Edge on Windows hand the PDF to the Windows share sheet,
    // where WhatsApp Desktop is listed.
    if (blob && typeof navigator !== "undefined" && typeof navigator.share === "function") {
        const file = new File([blob], filename, { type: "application/pdf" });
        if (navigator.canShare?.({ files: [file] })) {
            // The PDF on its own, never together with the message. Handed
            // both, WhatsApp keeps the text and drops the file -- which is how
            // statements kept arriving as text only. The message goes to the
            // clipboard instead, to paste as the document's caption.
            if (text && navigator.clipboard?.writeText) {
                try {
                    await navigator.clipboard.writeText(text);
                } catch (_) {
                    // No clipboard access: the PDF still goes, just without it.
                }
            }
            try {
                await navigator.share({ files: [file], title: filename });
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
    const params = query({ phone, text });
    const a = document.createElement("a");
    a.href = `whatsapp://send${params ? "?" + params : ""}`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    explainTextOnly(_t("This browser cannot hand a file to WhatsApp, so only the message was sent."));
    return "text";
}
