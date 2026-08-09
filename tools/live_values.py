"""Live pick-lists for the import templates.

A blank column in a spreadsheet is a guessing game: the shop owner has to know
that the unit is spelled "kg" and not "Kg", that the category is
"Goods / Beverages" and not "Beverages", that a vendor must already exist. Every
one of those guesses fails the import with "No matching record found".

So the templates are generated per download, out of the database the user is
actually importing into, and every name-matched column gets a real dropdown
holding the values that exist right now. Nothing has to be remembered or typed.

Two deliberate choices:

  * The dropdowns DO NOT reject other input (show_error is off in the builder).
    They are a help, not a cage: a user importing brand-new categories in the
    same file must still be able to type a name that does not exist yet.
  * Values live on a visible "Valid Values" sheet and the validation points at
    that range. An inline Excel list is capped at 255 characters, which barely
    holds a dozen categories, and a hidden sheet would stop anyone reading the
    list in LibreOffice or Google Sheets, where dropdowns render inconsistently.
"""

# Excel copes with far more, but a dropdown you have to scroll for two minutes
# is not a help. Past this the user is better served by the Valid Values sheet.
MAX_VALUES = 400


def _names(records, field='display_name'):
    seen, out = set(), []
    for record in records:
        value = record[field]
        if value and value not in seen:
            seen.add(value)
            out.append(value)
    return sorted(out)[:MAX_VALUES]


def units(env):
    return _names(env['uom.uom'].search([]), 'name')


def units_for_length_and_pack(env):
    """Every active unit: a package can be built on any of them."""
    return units(env)


def product_categories(env):
    # complete_name is the full path ("Goods / Beverages"), which is what the
    # importer matches on for a nested category.
    return _names(env['product.category'].search([]), 'complete_name')


def pos_categories(env):
    return _names(env['pos.category'].search([]), 'name')


def brands(env):
    model = env.get('product.brand')
    return _names(model.search([]), 'name') if model is not None else []


def sale_taxes(env):
    return _names(env['account.tax'].search([('type_tax_use', '=', 'sale')]), 'name')


def vendors(env):
    return _names(env['res.partner'].search([('supplier_rank', '>', 0)]), 'display_name')


def sellable_products(env):
    return _names(env['product.template'].search([('sale_ok', '=', True)]), 'display_name')


def product_types(env):
    return [label for _value, label in env['product.template']._fields['type'].selection]


def yes_no(env):
    return ['TRUE', 'FALSE']


# technical field name -> callable(env) -> list of valid values.
# A field absent from here simply gets no dropdown.
SOURCES = {
    'uom_id': units,
    'uom_ids': units,
    'categ_id': product_categories,
    'pos_categ_ids': pos_categories,
    'brand_id': brands,
    'taxes_id': sale_taxes,
    'seller_ids/partner_id': vendors,
    'product_id': sellable_products,
    'parent_id': None,          # filled per template, differs by model
    'relative_uom_id': units,
    'type': product_types,
    'available_in_pos': yes_no,
    'sale_ok': yes_no,
    'purchase_ok': yes_no,
    'is_storable': yes_no,
}

# parent_id means a different thing on each category model, so it is resolved
# by template key rather than by field name.
PARENT_SOURCES = {
    'product_category': product_categories,
    'pos_category': pos_categories,
}


def source_for(field, template_key):
    if field == 'parent_id':
        return PARENT_SOURCES.get(template_key)
    return SOURCES.get(field)
