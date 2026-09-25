"""Import the Paints sheet of "Murshid Store.xlsx" as a shared catalogue.

    venv/Scripts/python.exe odoo/odoo-bin shell -c odoo.conf -d <db> --no-http \
        < custom_addons/pos_retail/scripts/import_paints.py

On the server (copy the workbook to /tmp first so the odoo user can read it):
    sudo -u odoo env PAINTS_XLSX="/tmp/Murshid Store.xlsx" \
        /opt/odoo/venv/bin/python3 /opt/odoo/odoo/odoo-bin shell \
        -c /etc/odoo/odoo.conf -d ostore_live --no-http \
        < /opt/odoo/custom_addons/pos_retail/scripts/import_paints.py

DRY RUN by default. Set APPLY = True (or pipe through
sed 's/^APPLY = False/APPLY = True/') to write.

What it does:
  * products are shared by every branch (no company, no "Sell in Branches"),
    named "<name> (<size>) - <brand>" because the sheet repeats the same
    colour and size under different brands
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

import os
import re

import openpyxl

APPLY = False
XLSX = os.environ.get('PAINTS_XLSX', r'C:\Users\THINKBOOK\Downloads\Murshid Store.xlsx')
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
    'elite': 'Elite', 'exclusive nelson': 'Exclusive Nelson',
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
wb = openpyxl.load_workbook(XLSX, read_only=True, data_only=True)
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
    display = name + (f" ({size})" if size else '') + (f" - {brand}" if brand else '')
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

    companies = env['res.company'].sudo().search([])
    pos_paints = PosCategory.search([('name', '=', 'Paints')], limit=1) or PosCategory.create({'name': 'Paints'})
    created = updated = 0
    with env.cr.savepoint():
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
            xmlid = f"paint_{key}"
            existing = IMD.search([('module', '=', XMLID_MODULE), ('name', '=', xmlid),
                                   ('model', '=', 'product.template')], limit=1)
            template = Template.browse(existing.res_id).exists() if existing else Template
            if template:
                template.write(vals)
                updated += 1
            else:
                template = Template.create(vals)
                IMD.create({'module': XMLID_MODULE, 'name': xmlid, 'model': 'product.template',
                            'res_id': template.id, 'noupdate': True})
                created += 1
            # Cost is company-dependent in Odoo 19: written once, it would exist
            # only for whichever company ran the script and read 0 in every
            # branch. Shared products need it in each company.
            for company in companies:
                template.with_company(company).standard_price = p['cost']
    env.cr.commit()
    no_barcode = Template.search_count([('id', 'in', IMD.search([('module', '=', XMLID_MODULE), ('name', '=like', 'paint\\_%')]).mapped('res_id')),
                                        ('barcode', '=', False)])
    print(f"created {created}, updated {updated}; products still without a barcode: {no_barcode}")
    print("=" * 78)
