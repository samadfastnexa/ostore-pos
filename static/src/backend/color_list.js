/** @odoo-module **/

import { _t } from "@web/core/l10n/translation";
import { ColorList } from "@web/core/colorlist/colorlist";

// Odoo ships a fixed palette of twelve (see web/static/src/core/colorlist),
// all of them mid-tone pastels chosen so a dark label stays readable on top.
// A hardware counter carries several sizes of the same fitting side by side,
// and twelve soft tints is not enough separation to pick one out at a glance,
// so this appends a darker, more saturated set.
//
// ORDER IS THE CONTRACT. The stored value is a plain integer index into this
// array, so appending is safe but inserting or reordering silently repaints
// every product already coloured. Each index below is styled by number in
// static/src/backend/color_list.scss (the picker swatch) and
// static/src/overrides/color_list_pos.scss (the till button); adding an entry
// here without adding both rules leaves an unstyled, invisible swatch.
const POS_RETAIL_EXTRA_COLORS = [
    _t("Black"),      // 12
    _t("Grey"),       // 13
    _t("Brown"),      // 14
    _t("Maroon"),     // 15
    _t("Navy"),       // 16
    _t("Forest"),     // 17
    _t("Brass"),      // 18
    _t("Slate"),      // 19
];

// Guarded because an asset bundle can be evaluated more than once in a single
// browser session (hot reload in dev, a second POS window). Appending twice
// would duplicate the swatches and, worse, shift no indices but render two
// buttons claiming the same value.
if (!ColorList.posRetailExtended) {
    ColorList.posRetailExtended = true;
    ColorList.COLORS = [...ColorList.COLORS, ...POS_RETAIL_EXTRA_COLORS];
}
