"""Import the "Bahria Paints" tab of the Murshid Store Google Sheet.

    venv/Scripts/python.exe odoo/odoo-bin shell -c odoo.conf -d <db> --no-http \
        < custom_addons/pos_retail/scripts/import_paints.py

On the server:
    sudo -u odoo /opt/odoo/venv/bin/python3 /opt/odoo/odoo/odoo-bin shell \
        -c /etc/odoo/odoo.conf -d ostore_live --no-http \
        < /opt/odoo/custom_addons/pos_retail/scripts/import_paints.py

The source is the live Google Sheet (shared "anyone with the link can
view"), downloaded fresh on every run. Overrides, all optional (with sudo,
pass them as: sudo -u odoo env NAME=value ...):
    PAINTS_XLSX    a local .xlsx instead of the Google Sheet
    PAINTS_TAB     sheet tab to read            (default "Bahria Paints")
    PAINTS_BRANCH  branch that sells and stocks them (default "Bahria")

DRY RUN by default. Set APPLY = True (or pipe through
sed 's/^APPLY = False/APPLY = True/') to write.

What it does:
  * products named exactly as the sheet's Name column; name + size + brand
    identify a row, so the same colour under several brands or sizes stays
    separate products
  * Size goes into the product's Size field (shown on the till card)
  * sold at the branch only ("Sell in Branches"), visible in the back office
  * categories Paints > Distemper/Oil Paint > Drum/Gallon/Quarter, one POS
    category "Paints", brands merged across case and spelling variants
  * rows without a sales price import at 0, still sellable at the till
  * a min/MRP that contradicts the sales price is dropped for that row and
    reported, since pos_retail rejects min > price or MRP < price
  * "Pieces" becomes OPENING stock in the branch's warehouse, only for a
    product with no stock movement there yet. Once a product has been
    counted, sold or received, re-runs never touch its stock again -- the
    sheet is a price list after that, not a stock count.
  * safe to re-run: each product carries an external id, so a re-run
    updates in place. Barcodes are generated on first create, never changed;
    the sheet's own BARCODE column is ignored on purpose.
"""

import io
import os
import re
import time
import urllib.request

import openpyxl

APPLY = False
SHEET_URL = ('https://docs.google.com/spreadsheets/d/'
             '1wyP6KnQO5LowvsHZoHM4rntFwyJA8Wc5Kc652SXJDtI/export?format=xlsx')
XLSX = os.environ.get('PAINTS_XLSX', SHEET_URL)
SHEET = os.environ.get('PAINTS_TAB', 'Bahria Paints')
BRANCH = os.environ.get('PAINTS_BRANCH', 'Bahria')
XMLID_MODULE = '__import__'

# The size and brand spellings below are also part of each product's
# external id. Changing an existing mapping re-keys those products, and the
# next run would create them again as duplicates -- only ever ADD entries.
SIZES = {
    'gallon': 'Gallon', 'quarter': 'Quarter', 'drum': 'Drum',
    'adha pound': 'Half Pound', 'half liter': 'Half Litre',
    '4 inche': '4 Inch', '4 inchi': '4 Inch', '5 inchi': '5 Inch',
}
BRANDS = {
    'advacne': 'Advance', 'advance series': 'Advance',
    'black and white': 'Black and White', 'captain': 'Captain', 'commander': 'Commander',
    'elite': 'Elite', 'exclusive nelson': 'Exclusive Nelson', 'nelson exclusive': 'Exclusive Nelson',
    'fine coat': 'Finecoat', 'finecoat': 'Finecoat',
    'finecoat/ makro': 'Makro / Finecoat', 'makro/fincoat': 'Makro / Finecoat',
    'marko/fincoat': 'Makro / Finecoat',
    'fish': 'Fish', 'glide': 'Glide', "gobi's": "Gobi's", 'group master': 'Group Master',
    'jotun': 'Jotun', 'kent tone': 'Kent Tone', 'local': 'Local', 'makro': 'Makro',
    'murshid colors': 'Murshid Colors', 'nelson': 'Nelson', 'nelson extra': 'Nelson Extra',
    'silicon master paint': 'Silicon Master Paint', 'sooper': 'Sooper', 'universal': 'Universal',
}
CATEGORY_WORDS = {'distamber': 'Distemper', 'oilpant': 'Oil Paint', 'oilpaint': 'Oil Paint'}


def clean(value):
    if value is None:
        return ''
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    return re.sub(r'\s+', ' ', str(value)).strip()


def number(value):
    return float(value) if isinstance(value, (int, float)) else 0.0


def category_path(raw):
    if not clean(raw):
        return ['Paints']
    return [CATEGORY_WORDS.get(part.strip().lower(), part.strip().title())
            for part in str(raw).split('/') if part.strip()]


def slug(*parts):
    return re.sub(r'[^a-z0-9]+', '_', ' '.join(parts).lower()).strip('_')


# ---------- read ----------
if XLSX.startswith('http'):
    with urllib.request.urlopen(XLSX, timeout=60) as response:
        payload = response.read()
    if not payload.startswith(b'PK'):
        raise SystemExit("The sheet did not download as a spreadsheet -- is it still shared "
                         "'Anyone with the link can view'?")
    source = io.BytesIO(payload)
else:
    source = XLSX
wb = openpyxl.load_workbook(source, read_only=True, data_only=True)
if SHEET not in wb.sheetnames:
    raise SystemExit(f"No tab named {SHEET!r} in the sheet (was it renamed?). Tabs: {wb.sheetnames}. "
                     f"Pass the right one as PAINTS_TAB.")
rows = list(wb[SHEET].iter_rows(values_only=True))
header = [clean(h).lower() for h in rows[0]]
col = {name: header.index(name) for name in header if name}

products, notes = {}, []
for rownum, row in enumerate(rows[1:], start=2):
    get = lambda name: row[col[name]] if col.get(name) is not None and col[name] < len(row) else None
    name = clean(get('name'))
    if not name:
        continue
    size_raw = clean(get('size')).lower()
    size = SIZES.get(size_raw, clean(get('size')).title())
    brand_raw = clean(get('brand'))
    brand = BRANDS.get(brand_raw.lower(), brand_raw.title()) if brand_raw and brand_raw.lower() != 'none' else ''
    price, cost = number(get('sales price')), number(get('cost'))
    minimum, mrp = number(get('minimum selling price')), number(get('maximum retail price (mrp)'))
    if price and ((minimum and minimum > price) or (mrp and mrp < price)):
        notes.append(f"row {rownum}: {name} ({size}) price {price:g} vs min {minimum:g} / MRP {mrp:g}: "
                     f"range dropped, fix it in the sheet")
        minimum = mrp = 0.0
    if minimum and mrp and minimum > mrp:
        notes.append(f"row {rownum}: {name} min {minimum:g} above MRP {mrp:g}: range dropped")
        minimum = mrp = 0.0
    raw_pieces = get('pieces')
    pieces = None
    if isinstance(raw_pieces, (int, float)):
        pieces = float(raw_pieces)
        if pieces < 0:
            notes.append(f"row {rownum}: {name} Pieces is negative ({pieces:g}): no stock loaded")
            pieces = None
    elif clean(raw_pieces):
        notes.append(f"row {rownum}: {name} Pieces is {clean(raw_pieces)!r}, not a number: no stock loaded")
    else:
        notes.append(f"row {rownum}: {name} Pieces is empty: no stock loaded")
    # Name exactly as the sheet has it (the owner's wording). Size and brand
    # still tell same-named rows apart in the external id.
    display = str(get('name')).strip() if isinstance(get('name'), str) else name
    key = slug(name, size, brand)
    if key in products:
        # Same item counted on two lines of the stock sheet: the shelf holds both.
        first = products[key]
        before = first['pieces']
        if pieces is not None:
            first['pieces'] = (before or 0.0) + pieces
        notes.append(f"row {rownum}: same name/size/brand as row {first['row']}, merged into it; "
                     f"pieces added: {before if before is not None else 0:g} + {pieces or 0:g} = "
                     f"{first['pieces'] or 0:g} (fix the sheet if it was a duplicate entry)")
        continue
    products[key] = {
        'row': rownum, 'name': display, 'size': size, 'brand': brand, 'price': price, 'cost': cost,
        'minimum': minimum, 'mrp': mrp, 'pieces': pieces, 'categ': category_path(get('product category')),
    }

# ---------- branch and warehouse ----------
branch = env['res.company'].sudo().search([('name', 'ilike', BRANCH), ('child_ids', '=', False)])
if len(branch) != 1:
    raise SystemExit(f"Expected exactly one branch matching {BRANCH!r}, found "
                     f"{branch.mapped('name') or 'none'}. Pass the right one as PAINTS_BRANCH.")
warehouse = env['stock.warehouse'].sudo().search([('company_id', '=', branch.id)], limit=1)
if not warehouse:
    raise SystemExit(f"{branch.name} has no warehouse to hold the opening stock.")

previous = {
    imd.name[len('paint_'):]: imd.res_id
    for imd in env['ir.model.data'].sudo().search([
        ('module', '=', XMLID_MODULE), ('model', '=', 'product.template'), ('name', '=like', 'paint\\_%')])
}


def has_stock_history(templates):
    """Templates with any stock movement in the branch -- their stock is live."""
    variants = templates.product_variant_ids
    if not variants:
        return env['product.template']
    moved = env['stock.move'].sudo()._read_group(
        [('product_id', 'in', variants.ids), ('company_id', '=', branch.id), ('state', '!=', 'cancel')],
        ['product_id'])
    return env['product.template'].browse({product.product_tmpl_id.id for (product,) in moved})


existing_templates = env['product.template'].sudo().browse(
    [previous[k] for k in products if k in previous]).exists()
live = has_stock_history(existing_templates)
stock_rows = [p for k, p in products.items() if p['pieces']]
stock_todo = [p for k, p in products.items()
              if p['pieces'] and not (k in previous and previous[k] in live.ids)]

print()
print("=" * 78)
print("IMPORT PAINTS" + ("" if APPLY else "   (DRY RUN -- nothing written)"))
print("=" * 78)
print(f"source: {XLSX}  [tab {SHEET!r}]")
print(f"branch: {branch.name}  |  warehouse: {warehouse.name}")
print(f"{len(products)} products  |  {sum(1 for p in products.values() if not p['price'])} without a sales price (import at 0)")
print(f"sizes: {sorted({p['size'] for p in products.values() if p['size']})}")
print(f"brands: {sorted({p['brand'] for p in products.values() if p['brand']})}")
print(f"categories: {sorted({' / '.join(p['categ']) for p in products.values()})}")
print(f"opening stock: {len(stock_todo)} products, {sum(p['pieces'] for p in stock_todo):g} pieces"
      + (f"  ({len(stock_rows) - len(stock_todo)} skipped: already have stock history in {branch.name})"
         if len(stock_rows) != len(stock_todo) else ""))
for n in notes:
    print("  note:", n)

new_keys = [k for k in products if k not in previous]
gone = env['product.template'].sudo().with_context(active_test=False).browse(
    [res_id for key, res_id in previous.items() if key not in products]).exists()
print(f"{len(new_keys)} new, {len(products) - len(new_keys)} already imported (will be updated)")
if gone:
    # Not deleted: a product may already be on receipts or in stock. A renamed
    # row in the sheet shows up here as one "gone" plus one "new".
    print(f"{len(gone)} previously imported paint(s) are no longer in the sheet "
          f"(renamed or removed); left untouched, archive them by hand if unwanted:")
    for t in gone.sorted('name'):
        print(f"    - {t.name} {t.pos_retail_size or ''}  [{t.barcode or 'no barcode'}]")

if not APPLY:
    for p in list(products.values())[:8]:
        print(f"  e.g. {p['name']:34s} {p['size']:10s} {p['brand']:18s} price {p['price']:>7g}  "
              f"pieces {p['pieces'] if p['pieces'] is not None else '-'}")
    print("=" * 78)
    print("Nothing was written. Set APPLY = True to import.")
    print("=" * 78)
else:
    Category = env['product.category'].sudo()
    PosCategory = env['pos.category'].sudo()
    Brand = env['product.brand'].sudo()
    Template = env['product.template'].sudo()
    IMD = env['ir.model.data'].sudo()

    def category(path):
        parent = Category.browse()
        for name in path:
            found = Category.search([('name', '=', name), ('parent_id', '=', parent.id or False)], limit=1)
            parent = found or Category.create({'name': name, 'parent_id': parent.id or False})
        return parent

    brands = {}

    def brand(name):
        if not name:
            return False
        if name not in brands:
            found = Brand.with_context(active_test=False).search([('name', '=ilike', name)], limit=1)
            brands[name] = found or Brand.create({'name': name})
        return brands[name].id

    def changes(template, vals):
        """Only the fields that actually differ.

        Products and variants carry full-mode audit rules, which read every
        field before and after each write; rewriting an unchanged product
        costs the same as a real edit and fills the audit log with noise.
        """
        diff = {}
        for field, value in vals.items():
            current = template[field]
            if isinstance(value, list):  # [(6, 0, ids)] on a many2many
                if set(current.ids) != set(value[0][2]):
                    diff[field] = value
            elif hasattr(current, '_name'):
                if current.id != (value or False):
                    diff[field] = value
            elif isinstance(value, float):
                if abs((current or 0.0) - value) > 0.001:
                    diff[field] = value
            elif (current or False) != (value or False):
                diff[field] = value
        return diff

    companies = env['res.company'].sudo().search([])
    pos_paints = PosCategory.search([('name', '=', 'Paints')], limit=1) or PosCategory.create({'name': 'Paints'})
    started = time.monotonic()
    print("importing... (nothing is saved until the end; don't interrupt)", flush=True)
    with env.cr.savepoint():
        to_create, costs, updated, unchanged, templates_by_key = [], [], 0, 0, {}
        for key, p in products.items():
            vals = {
                'name': p['name'], 'pos_retail_size': p['size'] or False, 'list_price': p['price'],
                'minimum_selling_price': p['minimum'], 'mrp': p['mrp'],
                'categ_id': category(p['categ']).id, 'pos_categ_ids': [(6, 0, pos_paints.ids)],
                'pos_retail_branch_ids': [(6, 0, branch.ids)],
                'brand_id': brand(p['brand']),
                'type': 'consu', 'is_storable': True,
                'available_in_pos': True, 'sale_ok': True, 'purchase_ok': True,
                'company_id': False,
            }
            template = Template.browse(previous.get(key)).exists()
            if template:
                diff = changes(template, vals)
                if diff:
                    template.write(diff)
                    updated += 1
                else:
                    unchanged += 1
                costs.append((template, p['cost']))
                templates_by_key[key] = template
            else:
                to_create.append((key, vals, p['cost']))
        print(f"  checked existing products ({time.monotonic() - started:.0f}s)", flush=True)

        if to_create:
            new_templates = Template.create([vals for _key, vals, _cost in to_create])
            IMD.create([{'module': XMLID_MODULE, 'name': f"paint_{key}", 'model': 'product.template',
                         'res_id': tmpl.id, 'noupdate': True}
                        for (key, _vals, _cost), tmpl in zip(to_create, new_templates)])
            costs += [(tmpl, cost) for (_key, _vals, cost), tmpl in zip(to_create, new_templates)]
            templates_by_key.update({key: tmpl for (key, _v, _c), tmpl in zip(to_create, new_templates)})
            print(f"  created {len(new_templates)} ({time.monotonic() - started:.0f}s)", flush=True)

        # Cost is company-dependent in Odoo 19: set once it would exist only
        # for the company running the script and read 0 in every branch.
        # Grouped by value so each company takes one write per distinct cost.
        cost_writes = 0
        for company in companies:
            groups = {}
            for tmpl, cost in costs:
                if abs(tmpl.with_company(company).standard_price - cost) > 0.001:
                    groups.setdefault(cost, Template.browse())
                    groups[cost] |= tmpl
            for cost, tmpls in groups.items():
                tmpls.with_company(company).write({'standard_price': cost})
                cost_writes += len(tmpls)
        print(f"  costs set ({time.monotonic() - started:.0f}s)", flush=True)

        # Opening stock, re-checked against live history inside the
        # transaction rather than trusting the report computed above.
        wanted = {templates_by_key[k]: p['pieces'] for k, p in products.items() if p['pieces']}
        live = has_stock_history(Template.browse([t.id for t in wanted]))
        counted = {t: qty for t, qty in wanted.items() if t not in live}
        if counted:
            Quant = env['stock.quant'].sudo().with_company(branch).with_context(inventory_mode=True)
            quants = Quant.create([{
                'product_id': tmpl.product_variant_id.id,
                'location_id': warehouse.lot_stock_id.id,
                'inventory_quantity': qty,
            } for tmpl, qty in counted.items()])
            result = quants.action_apply_inventory()
            if isinstance(result, dict):
                raise SystemExit("Odoo asked to resolve an inventory conflict; nothing was saved. "
                                 "Check Inventory > Physical Inventory for this branch.")
        print(f"  opening stock set ({time.monotonic() - started:.0f}s)", flush=True)
    env.cr.commit()
    no_barcode = Template.search_count([('id', 'in', [t.id for t in templates_by_key.values()]),
                                        ('barcode', '=', False)])
    print(f"created {len(to_create)}, updated {updated}, unchanged {unchanged}, "
          f"cost changes {cost_writes}, opening stock for {len(counted)} products "
          f"({sum(counted.values()):g} pieces, {len(wanted) - len(counted)} skipped: stock already live); "
          f"products without a barcode: {no_barcode}  [{time.monotonic() - started:.0f}s]")
    print("=" * 78)
