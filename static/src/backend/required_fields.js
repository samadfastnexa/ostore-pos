/** @odoo-module **/

import { patch } from "@web/core/utils/patch";
import { FormLabel } from "@web/views/form/form_label";
import { Field, fieldVisualFeedback } from "@web/views/fields/field";

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

        // fieldVisualFeedback only evaluates the VIEW's required modifier, and
        // Odoo's arches almost never set one: a product's name and unit, an
        // expense's amount and category are all required on the MODEL and
        // carry nothing in the arch. Reading only the view modifier therefore
        // marks almost nothing, which is exactly how a form ends up looking
        // like it has no mandatory fields at all.
        const modelField = this.props.record.fields?.[this.props.fieldName];
        const isRequired = required || Boolean(modelField?.required);

        // A readonly field cannot be filled in, so marking it required would
        // be an instruction the user cannot act on.
        if (isRequired && !readonly) {
            return `${classes} o_pos_retail_required`.trim();
        }
        return classes;
    },
});

// Same blind spot on the input itself: Odoo's own `o_required_modifier`
// class (the one that tints the border) is also driven by the view modifier
// alone, so a model-required field gets no visual treatment either. Tag those
// so the stylesheet can outline them while they are still empty.
patch(Field.prototype, {
    get classNames() {
        const classNames = super.classNames;
        const modelField = this.props.record.fields?.[this.props.name];
        if (modelField?.required) {
            return `${classNames} o_pos_retail_required_field`.trim();
        }
        return classNames;
    },
});
