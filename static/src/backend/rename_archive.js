/** @odoo-module **/

import { translatedTermsGlobal } from "@web/core/l10n/translation";

// "Archive" is accountant's language. To the person behind the counter, being
// told to archive a product means nothing, and the fear is always the same one:
// have I just deleted it? The word has to answer that question by itself.
//
// Renamed through the translation table rather than by patching the five
// controllers that build these menu items (form, list, kanban, and the two
// confirmation dialogs). Every one of them goes through _t(), and _t() falls
// back to translatedTermsGlobal when the term is not in the loaded language
// (see web/core/l10n/translation.js, the lookup at the end of TranslatedString:
//   translatedTerms[context]?.[source] ?? translatedTermsGlobal[source] ?? source
// ). One entry per term therefore renames it everywhere at once, and nothing
// core does is overridden, so this survives an Odoo upgrade.
//
// Note the records are NOT deleted and NOT changed -- only the wording is. The
// underlying `active` flag, the "Archived" search filter and every report keep
// working exactly as before.
Object.assign(translatedTermsGlobal, {
    Archive: "Hide",
    Unarchive: "Unhide",
    // The confirmations say what actually happens, because "are you sure" on
    // its own invites the assumption that something is about to be destroyed.
    "Are you sure that you want to archive this record?":
        "Hide this? It stays in the system with all its history, and you can unhide it at any time.",
    "Are you sure that you want to archive all the selected records?":
        "Hide the selected items? They stay in the system with all their history, and you can unhide them at any time.",
});
