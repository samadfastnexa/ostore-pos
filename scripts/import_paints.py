"""Import the Paints sheet of "Murshid Store.xlsx" as a shared catalogue.

    venv/Scripts/python.exe odoo/odoo-bin shell -c odoo.conf -d <db> --no-http \
        < custom_addons/pos_retail/scripts/import_paints.py

On the server:
    sudo -u odoo /opt/odoo/venv/bin/python3 /opt/odoo/odoo/odoo-bin shell \
        -c /etc/odoo/odoo.conf -d ostore_live --no-http \
        < /opt/odoo/custom_addons/pos_retail/scripts/import_paints.py

The source is the live Google Sheet (shared "anyone with the link can
view"), downloaded fresh on every run. To use a local file instead, pass
PAINTS_XLSX=<path> (with sudo: sudo -u odoo env PAINTS_XLSX=<path> ...).

DRY RUN by default. Set APPLY = True (or pipe through
sed 's/^APPLY = False/APPLY = True/') to write.

What it does:
  * products are shared by every branch (no company, no "Sell in Branches"),
    named exactly as the sheet's Name column; name + size + brand identify a
    row, so the same colour under several brands stays separate products
  * categories Paints > Distemper/Oil Paint > Drum/Gallon/Quarter, one POS
    category "Paints", brands merged across case and spelling variants
  * rows without a sales price import at 0, still sellable at the till
  * a min/MRP that contradicts the sales price is dropped for that row and
    reported, since pos_retail rejects min > price or MRP < price
  * the "Pieces" column (stock) is NOT loaded: stock belongs to one branch's
    warehouse, and the sheet does not say which
  * safe to re-run: each product carries an external id, so a second run
    updates prices/names in place instead of creating duplicates. Barcodes
    are generated on first create and never overwritten.
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
SHEET = 'Paints'
XMLID_MODULE = '__import__'

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
    # Name exactly as the sheet has it (the owner's wording). Size and brand
    # still tell same-named rows apart in the external id and brand field.
    display = str(get('name')).strip() if isinstance(get('name'), str) else name
    key = slug(name, size, brand)
    if key in products:
        notes.append(f"row {rownum}: same name/size/brand as row {products[key]['row']}, merged into it")
        continue
    products[key] = {
        'row': rownum, 'name': display, 'brand': brand, 'price': price, 'cost': cost,
        'minimum': minimum, 'mrp': mrp, 'categ': category_path(get('product category')),
    }

print()
print("=" * 78)
print("IMPORT PAINTS" + ("" if APPLY else "   (DRY RUN -- nothing written)"))
print("=" * 78)
print(f"source: {XLSX}")
print(f"{len(products)} products  |  {sum(1 for p in products.values() if not p['price'])} without a sales price (import at 0)")
print(f"brands: {sorted({p['brand'] for p in products.values() if p['brand']})}")
print(f"categories: {sorted({' / '.join(p['categ']) for p in products.values()})}")
for n in notes:
    print("  note:", n)

previous = {
    imd.name[len('paint_'):]: imd.res_id
    for imd in env['ir.model.data'].sudo().search([
        ('module', '=', XMLID_MODULE), ('model', '=', 'product.template'), ('name', '=like', 'paint\\_%')])
}
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
        print(f"    - {t.name}  [{t.barcode or 'no barcode'}]")

if not APPLY:
    for p in list(products.values())[:8]:
        print(f"  e.g. {p['name']:48s} price {p['price']:>8g}  cost {p['cost']:>8g}  {' / '.join(p['categ'])}")
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
            if field == 'pos_categ_ids':
                if set(current.ids) != set(value[0][2]):
                    diff[field] = value
            elif hasattr(current, '_name'):
                if current.id != (value or False):
                    diff[field] = value
            elif isinstance(value, float):
                if abs((current or 0.0) - value) > 0.001:
                    diff[field] = value
            elif current != value:
                diff[field] = value
        return diff

    companies = env['res.company'].sudo().search([])
    pos_paints = PosCategory.search([('name', '=', 'Paints')], limit=1) or PosCategory.create({'name': 'Paints'})
    started = time.monotonic()
    existing = {imd.name: imd.res_id for imd in IMD.search([
        ('module', '=', XMLID_MODULE), ('model', '=', 'product.template'), ('name', '=like', 'paint\\_%')])}
    print("importing... (nothing is saved until the end; don't interrupt)", flush=True)
    with env.cr.savepoint():
        to_create, costs, updated, unchanged = [], [], 0, 0
        for key, p in products.items():
            vals = {
                'name': p['name'], 'list_price': p['price'],
                'minimum_selling_price': p['minimum'], 'mrp': p['mrp'],
                'categ_id': category(p['categ']).id, 'pos_categ_ids': [(6, 0, pos_paints.ids)],
                'brand_id': brand(p['brand']),
                'type': 'consu', 'is_storable': True,
                'available_in_pos': True, 'sale_ok': True, 'purchase_ok': True,
                'company_id': False,
            }
            template = Template.browse(existing.get(f"paint_{key}")).exists()
            if template:
                diff = changes(template, vals)
                if diff:
                    template.write(diff)
                    updated += 1
                else:
                    unchanged += 1
                costs.append((template, p['cost']))
            else:
                to_create.append((key, vals, p['cost']))
        print(f"  checked existing products ({time.monotonic() - started:.0f}s)", flush=True)

        if to_create:
            new_templates = Template.create([vals for _key, vals, _cost in to_create])
            IMD.create([{'module': XMLID_MODULE, 'name': f"paint_{key}", 'model': 'product.template',
                         'res_id': tmpl.id, 'noupdate': True}
                        for (key, _vals, _cost), tmpl in zip(to_create, new_templates)])
            costs += [(tmpl, cost) for (_key, _vals, cost), tmpl in zip(to_create, new_templates)]
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
    env.cr.commit()
    no_barcode = Template.search_count([('id', 'in', IMD.search([('module', '=', XMLID_MODULE), ('name', '=like', 'paint\\_%')]).mapped('res_id')),
                                        ('barcode', '=', False)])
    print(f"created {len(to_create)}, updated {updated}, unchanged {unchanged}, "
          f"cost changes {cost_writes}; products still without a barcode: {no_barcode}  "
          f"[{time.monotonic() - started:.0f}s]")
    print("=" * 78)
