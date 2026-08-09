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
// Not every field the ORM calls required is something a person must fill in,
// and marking those spends the reader's attention without telling them
// anything.
//
//  - Boolean: a checkbox is never empty, it is true or false, so "required"
//    on one can never be acted upon.
//  - one2many / many2many: a required x2many is a modelling constraint (a
//    product template must own its variants), not a prompt to the user.
//
// Everything else stays marked, including fields that arrive with a default:
// they really are mandatory, and saying so is honest.
function isMeaningfullyRequired(modelField) {
    if (!modelField?.required) {
        return false;
    }
    return !["boolean", "one2many", "many2many"].includes(modelField.type);
}

// Odoo shows its "?" explanation icon only on fields that carry help text.
// Across a real Product, Customer or Invoice form roughly half to three
// quarters of the fields have none, so the icon appears in a scatter and the
// user cannot tell whether a missing "?" means "no explanation exists" or
// "nothing to explain".
//
// Curated help is always better and is used whenever it exists. This is the
// fallback for everything else: it describes what the field IS from what the
// server already told us -- the kind of value, whether it must be filled in,
// what it links to, what the choices are. It deliberately does not invent
// business meaning, because a confidently wrong explanation is worse than an
// honest description.
const TYPE_WORDS = {
    char: "Short text.",
    text: "Long text.",
    html: "Formatted text.",
    integer: "A whole number.",
    float: "A number.",
    monetary: "An amount of money.",
    boolean: "A yes/no tick box.",
    date: "A date.",
    datetime: "A date and time.",
    binary: "An attached file.",
    image: "An image.",
    selection: "Pick one of the listed options.",
    many2one: "Links to another record.",
    one2many: "A list of related records.",
    many2many: "Any number of related records.",
};

function describeField(modelField, fieldInfo) {
    if (!modelField) {
        return "";
    }
    const parts = [];

    if (modelField.type === "selection" && Array.isArray(modelField.selection)) {
        const choices = modelField.selection.map((option) => option[1]).filter(Boolean);
        parts.push(
            choices.length && choices.length <= 8
                ? `Pick one of: ${choices.join(", ")}.`
                : TYPE_WORDS.selection
        );
    } else if (["many2one", "one2many", "many2many"].includes(modelField.type)) {
        const target = modelField.relation_field_label || modelField.string;
        parts.push(
            modelField.type === "many2one"
                ? `Links to another record${target ? ` (${target})` : ""}.`
                : TYPE_WORDS[modelField.type]
        );
    } else {
        parts.push(TYPE_WORDS[modelField.type] || "");
    }

    if (modelField.required && !["boolean", "one2many", "many2many"].includes(modelField.type)) {
        parts.push("Must be filled in.");
    }
    // A computed, non-editable field is the single most common "why can't I
    // type here?" question, so it is worth saying plainly.
    if (modelField.readonly || fieldInfo?.readonly === "1" || fieldInfo?.readonly === "True") {
        parts.push("Worked out automatically; you cannot type into it.");
    }

    return parts.filter(Boolean).join(" ");
}

patch(FormLabel.prototype, {
    get tooltipHelp() {
        // Curated help always wins; this only fills the silence.
        const curated = super.tooltipHelp;
        if (curated) {
            return curated;
        }
        return describeField(
            this.props.record.fields?.[this.props.fieldName],
            this.props.fieldInfo
        );
    },

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
        const isRequired = required || isMeaningfullyRequired(modelField);

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
        if (isMeaningfullyRequired(modelField)) {
            // NOTE: Field.classNames returns an OBJECT of {class: bool}, not a
            // string (field.js, `return classNames` after building a literal).
            // Appending to it as a string yields "[object Object] ..." and
            // wipes o_field_widget, o_field_empty and the widget-type class
            // off every field in the backend. Set a key instead.
            classNames.o_pos_retail_required_field = true;
        }
        return classNames;
    },
});
