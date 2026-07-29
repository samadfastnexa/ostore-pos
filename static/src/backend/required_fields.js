/** @odoo-module **/

import { patch } from "@web/core/utils/patch";
import { FormLabel } from "@web/views/form/form_label";
import { fieldVisualFeedback } from "@web/views/fields/field";

// Mark required fields on the label.
//
// Odoo 19's only cue that a field is mandatory is a faintly different border
// colour on the input, applied to the field widget. Shop staff filling in a
// product or a customer cannot see that, so they discover what was required
// by failing to save.
//
// FormLabel already computes `required` through fieldVisualFeedback and then
// discards it; this keeps it as a class, which required_fields.scss turns
// into an asterisk. Doing it on the label rather than guessing with CSS
// sibling selectors means the mark is right even in layouts where the label
// and the input are not adjacent.
patch(FormLabel.prototype, {
    get className() {
        const classes = super.className;
        const { required, readonly } = fieldVisualFeedback(
            this.props.fieldInfo.field,
            this.props.record,
            this.props.fieldName,
            this.props.fieldInfo
        );
        // A readonly field cannot be filled in, so marking it required would
        // be an instruction the user cannot act on.
        if (required && !readonly) {
            return `${classes} o_pos_retail_required`.trim();
        }
        return classes;
    },
});
