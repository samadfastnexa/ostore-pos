"""Import the Polish, Chemicals and Electric tabs of the Murshid Store Sheet.

The Bahria Paints tab is NOT handled here: scripts/import_paints.py owns it,
because production's paints were imported before rows had codes and need that
script's one-time matching by name. run_import_on_server.sh runs both.

Local dev run (no Bahria company locally, so name the branch):
    IMPORT_BRANCH="Branch 2" venv/Scripts/python.exe odoo/odoo-bin shell \
        -c odoo.conf -d OStore --no-http < custom_addons/pos_retail/scripts/import_categories.py

Server run: see run_import_on_server.sh.

DRY RUN by default -- prints what would change and writes nothing.

Environment overrides:
    APPLY=1              Actually write to the database
    IMPORT_XLSX          Local .xlsx file path or Google Sheet export URL
                         Defaults to the local file in Downloads if present, else the Google Sheet
    IMPORT_BRANCH        Branch name or id (default 'Bahria'); the run stops if it
                         does not match exactly one branch with a warehouse
    IMPORT_TABS          Comma-separated tabs to import, e.g. "Bahria Electric"
                         (default: all configured tabs)
    FORCE_STOCK=1        Re-count products already counted -- OVERWRITES live stock
                         (sales and receipts since the first count are lost)

Rules:
  * a row is a product only if its BARCODE is a sheet code (MBAHRIA0296...).
    Codes run on across tabs and identify a product for good; uncoded rows
    (e.g. paint rows pasted at the bottom of a tab) are skipped and listed.
  * product name exactly as in the sheet; size into the Size field
  * sold at the branch only; cost set for every company (company-dependent)
  * a price, cost or quantity carrying a unit ("750/kg", "480/lts", "115meter")
    creates the product in that unit (kg, L, m)
  * opening stock = the sheet's quantity, loaded once per product: anything
    already counted in the branch is never touched again (unless FORCE_STOCK)
"""

import datetime
import io
import os
import re
import sys
import time
import urllib.request
import openpyxl

# ---------------------------------------------------------------------------
# Configuration & Overrides
# ---------------------------------------------------------------------------
APPLY_ENV = os.environ.get('APPLY', '0').strip().lower()
APPLY = APPLY_ENV in ('1', 'true', 'yes', 'y')

GOOGLE_SHEET_URL = (
    'https://docs.google.com/spreadsheets/d/'
    '1wyP6KnQO5LowvsHZoHM4rntFwyJA8Wc5Kc652SXJDtI/export?format=xlsx'
)

# Pick source file: explicit env -> local downloads -> Google Sheet
LOCAL_DOWNLOAD = r'C:\Users\THINKBOOK\Downloads\Murshid Store (1).xlsx'
LOCAL_REPO_SHEET = r'import-data/murshid-store/google_sheet_latest.xlsx'

if os.environ.get('IMPORT_XLSX'):
    XLSX = os.environ['IMPORT_XLSX']
elif os.path.exists(LOCAL_DOWNLOAD):
    XLSX = LOCAL_DOWNLOAD
elif os.path.exists(LOCAL_REPO_SHEET):
    XLSX = LOCAL_REPO_SHEET
else:
    XLSX = GOOGLE_SHEET_URL

BRANCH_NAME = os.environ.get('IMPORT_BRANCH', 'Bahria').strip()
XMLID_MODULE = '__import__'
FORCE_STOCK = os.environ.get('FORCE_STOCK', '0').strip().lower() in ('1', 'true', 'yes')

# Tab configuration
TABS_CONFIG = {
    'Bahria POLISH': {
        'name_col': 'Name',
        'size_col': 'SIZE',
        'qty_col': 'Quantity',
        'cost_col': 'COST',
        'price_col': 'SALES PRICE',
        'min_col': 'Minimum Selling Price',
        'mrp_col': 'Maximum Retail Price (MRP)',
        'categ_col': 'Product Category',
        'pos_categ_col': 'Point of Sale Category',
        'barcode_col': 'BARCODE',
        'brand_col': 'Brand',
        'unit_col': 'Unit',
        'default_pos_categ': 'Paints',
        'default_categ': 'Paints / Polish',
        'xmlid_prefix': 'polish',
    },
    'Bahria Chemicals': {
        'name_col': 'Name',
        'size_col': 'SIZE',
        'qty_col': 'Quantity',
        'cost_col': 'COST',
        'price_col': 'SALES PRICE',
        'min_col': 'Minimum Selling Price',
        'mrp_col': 'Maximum Retail Price (MRP)',
        'categ_col': 'Product Category',
        'pos_categ_col': 'Point of Sale Category',
        'barcode_col': 'Barcode',
        'brand_col': 'BRAND',
        'unit_col': 'Unit',
        'default_pos_categ': 'Paints',
        'default_categ': 'Paints / Polish / Chemicals',
        'xmlid_prefix': 'chemical',
    },
    'Bahria Electric': {
        'name_col': 'Name',
        'size_col': 'AMP/WATT/VOLT',
        'qty_col': 'Pieces',
        'cost_col': 'COST',
        'price_col': 'SALES PRICE',
        'min_col': 'Minimum Selling Price',
        'mrp_col': 'Maximum Retail Price (MRP)',
        'categ_col': 'Product Category',
        'pos_categ_col': 'Point of Sale Category',
        'barcode_col': 'BARCODE',
        'brand_col': 'Brand',
        'unit_col': 'Unit',
        'default_pos_categ': 'Electric',
        'default_categ': 'Electric / Electric Items',
        'xmlid_prefix': 'electric',
    },
    # 'Bahria Paints' is imported by scripts/import_paints.py (see docstring).
}

selected_tabs_env = os.environ.get('IMPORT_TABS')
if selected_tabs_env:
    requested_names = [t.strip().lower() for t in selected_tabs_env.split(',') if t.strip()]
    TABS = {k: v for k, v in TABS_CONFIG.items() if k.lower() in requested_names or any(r in k.lower() for r in requested_names)}
else:
    TABS = TABS_CONFIG

# ---------------------------------------------------------------------------
# Normalization & Helpers
# ---------------------------------------------------------------------------
SIZES_MAP = {
    'gallon': 'Gallon', 'quarter': 'Quarter', 'drum': 'Drum',
    'adha pound': 'Half Pound', 'half liter': 'Half Litre',
    '4 inche': '4 Inch', '4 inchi': '4 Inch', '5 inchi': '5 Inch',
    '1/2': '1/2', '3/4': '3/4', '1/4': '1/4',
}

BRANDS_MAP = {
    'advacne': 'Advance', 'advance series': 'Advance',
    'black and white': 'Black and White', 'captain': 'Captain', 'commander': 'Commander',
    'elite': 'Elite', 'exclusive nelson': 'Exclusive Nelson', 'nelson exclusive': 'Exclusive Nelson',
    'fine coat': 'Finecoat', 'finecoat': 'Finecoat',
    'finecoat/ makro': 'Makro / Finecoat', 'makro/fincoat': 'Makro / Finecoat',
    'marko/fincoat': 'Makro / Finecoat', 'fish': 'Fish', 'glide': 'Glide',
    "gobi's": "Gobi's", 'group master': 'Group Master', 'jotun': 'Jotun',
    'kent tone': 'Kent Tone', 'local': 'Local', 'makro': 'Makro',
    'murshid colors': 'Murshid Colors', 'nelson': 'Nelson', 'nelson extra': 'Nelson Extra',
    'silicon master paint': 'Silicon Master Paint', 'sooper': 'Sooper', 'universal': 'Universal',
    'aqua': 'AQUA', 'arik-lux': 'Arik-Lux', 'brooks': 'Brooks', 'broox': 'Broox',
    'burq': 'Burq', 'china': 'China', 'classic': 'Classic', 'clopal': 'Clopal',
    'chinton': 'Chinton', 'daiichi': 'Daiichi', 'deco': 'Deco', 'diamond': 'Diamond',
    'excelent': 'Excellent', 'five star': 'Five Star', 'flud': 'Flud',
    'meezan': 'Meezan', 'max': 'MAX', 'schneider': 'Schneider',
}

CATEGORY_WORDS = {
    'distamber': 'Distemper', 'oilpant': 'Oil Paint', 'oilpaint': 'Oil Paint',
    'electric_items': 'Electric Items', 'brackets': 'Brackets', 'gasitems': 'Gas Items',
    'regmal': 'Regmal', 'handbrush': 'Handbrush', 'spraypaints': 'Spray Paints',
    'putty': 'Putty', 'chemicals': 'Chemicals', 'polish': 'Polish',
}

UNIT_WORDS = {
    'ft': 'ft', 'feet': 'ft', 'foot': 'ft',
    'm': 'm', 'meter': 'm', 'meters': 'm', 'metre': 'm', 'metres': 'm', 'mtr': 'm', 'mtrs': 'm',
    'kg': 'kg', 'kgs': 'kg', 'kilo': 'kg', 'kilos': 'kg',
    'l': 'L', 'lt': 'L', 'ltr': 'L', 'ltrs': 'L', 'lts': 'L', 'litr': 'L',
    'liter': 'L', 'liters': 'L', 'litre': 'L', 'litres': 'L',
}


def clean(value):
    if value is None:
        return ''
    if isinstance(value, datetime.datetime):
        return f"{value.month}/{value.day}"
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    return re.sub(r'\s+', ' ', str(value)).strip()


def parse_numeric_and_unit(value):
    """Number plus optional unit: 480 -> (480, ''), '480/lts' -> (480, 'L'),
    '160 rs/ft' -> (160, 'ft'), '7500.kg' -> (7500, 'kg'), '115meter' -> (115, 'm')."""
    if isinstance(value, (int, float)):
        return float(value), ''
    s = clean(value)
    if not s or s.lower() in ('none', '-'):
        return 0.0, ''
    s = re.sub(r'(\d)[oO](?=\D|$)', r'\g<1>0', s)  # typo: '35o' -> '350'
    match = re.search(r'\d+(?:\.\d+)?', s)
    if not match:
        return 0.0, ''
    num = float(match.group(0))
    if s.lstrip().startswith('-'):
        num = -num
    unit = next((UNIT_WORDS[w] for w in re.findall(r'[a-z]+', s.lower()) if w in UNIT_WORDS), '')
    return num, unit


def parse_qty(value):
    s = clean(value)
    if not s or s.lower() in ('none', '0', '0.0', '-'):
        return 0.0, ''
    return parse_numeric_and_unit(s)


def slug(*parts):
    return re.sub(r'[^a-z0-9]+', '_', ' '.join(parts).lower()).strip('_')


def category_path(raw, default_path):
    s = clean(raw)
    if not s:
        return [p.strip() for p in default_path.split('/') if p.strip()]
    parts = [p.strip() for p in str(s).split('/') if p.strip()]
    res = []
    for part in parts:
        low = part.lower()
        res.append(CATEGORY_WORDS.get(low, part.title()))
    return res


# ---------------------------------------------------------------------------
# Load Workbook
# ---------------------------------------------------------------------------
print("=" * 78)
print("MURSHID STORE CATALOGUE & STOCK IMPORT" + ("" if APPLY else "   (DRY RUN)"))
print("=" * 78)
print(f"Source file: {XLSX}")

if XLSX.startswith('http'):
    print("Downloading sheet from Google Sheets...", flush=True)
    with urllib.request.urlopen(XLSX, timeout=120) as response:
        payload = response.read()
    if not payload.startswith(b'PK'):
        raise SystemExit("The sheet did not download as an Excel file. Check URL or sharing permissions.")
    source = io.BytesIO(payload)
else:
    source = XLSX

wb = openpyxl.load_workbook(source, read_only=True, data_only=True)
print(f"Tabs in workbook: {wb.sheetnames}", flush=True)

# ---------------------------------------------------------------------------
# Branch & Warehouse Resolution
# ---------------------------------------------------------------------------
Company = env['res.company'].sudo()
Warehouse = env['stock.warehouse'].sudo()

branch = Company.browse()
if BRANCH_NAME.isdigit():
    branch = Company.search([('id', '=', int(BRANCH_NAME))], limit=1)

if not branch:
    # Branches only (a parent company sells nothing); exactly one must match.
    # No guessing: a wrong branch would put every product and its stock there.
    candidates = Company.search([('name', 'ilike', BRANCH_NAME), ('child_ids', '=', False)])
    if len(candidates) != 1:
        raise SystemExit(f"Expected exactly one branch matching {BRANCH_NAME!r}, found "
                         f"{candidates.mapped('name') or 'none'}. Pass the right one as IMPORT_BRANCH.")
    branch = candidates

warehouse = Warehouse.search([('company_id', '=', branch.id)], limit=1)
if not warehouse:
    raise SystemExit(f"{branch.name} has no warehouse to hold the opening stock.")

print(f"Target Branch:    {branch.name} (id={branch.id})")
print(f"Target Warehouse: {warehouse.name} (id={warehouse.id}, location={warehouse.lot_stock_id.name})")

# ---------------------------------------------------------------------------
# Model Helpers & Caches
# ---------------------------------------------------------------------------
Category = env['product.category'].sudo()
PosCategory = env['pos.category'].sudo()
Brand = env['product.brand'].sudo()
Template = env['product.template'].sudo()
IMD = env['ir.model.data'].sudo()
Uom = env['uom.uom'].sudo()
Quant = env['stock.quant'].sudo()
companies = Company.search([])

brand_cache = {}
def get_brand(name):
    if not name:
        return False
    clean_name = clean(name)
    if not clean_name or clean_name.lower() in ('none', '0', '-'):
        return False
    norm_name = BRANDS_MAP.get(clean_name.lower(), clean_name.title())
    key = norm_name.lower()
    if key not in brand_cache:
        found = Brand.with_context(active_test=False).search([('name', '=ilike', norm_name)], limit=1)
        if not found and APPLY:
            found = Brand.create({'name': norm_name})
        brand_cache[key] = found.id if found else False
    return brand_cache[key]


categ_cache = {}
def get_category(path_list):
    key = tuple(path_list)
    if key in categ_cache:
        return categ_cache[key]
    parent = Category.browse()
    for part in path_list:
        found = Category.search([('name', '=', part), ('parent_id', '=', parent.id or False)], limit=1)
        if not found and APPLY:
            found = Category.create({'name': part, 'parent_id': parent.id or False})
        parent = found or Category.browse()
    categ_cache[key] = parent
    return parent


pos_categ_cache = {}
def get_pos_category(name):
    if not name:
        return PosCategory.browse()
    key = clean(name).title()
    if key not in pos_categ_cache:
        found = PosCategory.search([('name', '=ilike', name)], limit=1)
        if not found and APPLY:
            found = PosCategory.create({'name': key})
        pos_categ_cache[key] = found or PosCategory.browse()
    return pos_categ_cache[key]


uom_cache = {}
def get_uom(unit_str):
    if not unit_str:
        return env.ref('uom.product_uom_unit', raise_if_not_found=False) or Uom.search([('name', 'in', ('Units', 'Unit'))], limit=1)
    key = unit_str.lower()
    if key not in uom_cache:
        target_name = 'Units'
        if key in ('m', 'meter', 'metre'):
            target_name = 'm'
        elif key in ('ft', 'feet', 'foot'):
            target_name = 'ft'
        elif key in ('kg', 'kgs'):
            target_name = 'kg'
        elif key in ('l', 'ltr', 'liter', 'litre', 'lts'):
            target_name = 'L'
        found = Uom.search([('name', '=ilike', target_name)], limit=1)
        if not found:
            found = env.ref('uom.product_uom_unit')
        uom_cache[key] = found
    return uom_cache[key]


def has_stock_history(templates, company_rec):
    """Find templates with already completed inventory adjustments in this company."""
    variants = templates.product_variant_ids
    if not variants:
        return Template.browse()
    counted = env['stock.move'].sudo()._read_group(
        [('product_id', 'in', variants.ids), ('company_id', '=', company_rec.id),
         ('is_inventory', '=', True), ('state', '=', 'done')],
        ['product_id'])
    return Template.browse({product.product_tmpl_id.id for (product,) in counted})


def diff_fields(template, vals):
    """Return dictionary of only fields whose values genuinely changed."""
    diff = {}
    for field, value in vals.items():
        current = template[field]
        if isinstance(value, list):
            # m2m format [(6, 0, ids)]
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


# ---------------------------------------------------------------------------
# Parse & Process Sheets
# ---------------------------------------------------------------------------
grand_created = 0
grand_updated = 0
grand_unchanged = 0
grand_stock_products = 0
grand_stock_pieces = 0.0

for tab_name, cfg in TABS.items():
    if tab_name not in wb.sheetnames:
        print(f"\nTab '{tab_name}' not found in workbook. Skipping.", flush=True)
        continue

    print(f"\n{'=' * 78}", flush=True)
    print(f"PROCESSING TAB: {tab_name}", flush=True)
    print(f"{'=' * 78}", flush=True)

    ws = wb[tab_name]
    rows = list(ws.iter_rows(values_only=True))
    if not rows:
        print("  Empty tab.", flush=True)
        continue

    header_raw = [clean(h).lower() if h else '' for h in rows[0]]
    col_idx = {h: i for i, h in enumerate(header_raw) if h}

    def get_idx(col_key):
        name = cfg.get(col_key)
        if not name:
            return None
        return col_idx.get(name.lower(), None)

    name_i = get_idx('name_col')
    size_i = get_idx('size_col')
    qty_i = get_idx('qty_col')
    if qty_i is None:
        # The quantity-in-hand column has been renamed before (Pieces/QUANTITY).
        qty_i = col_idx.get('pieces', col_idx.get('quantity'))
    cost_i = get_idx('cost_col')
    price_i = get_idx('price_col')
    min_i = get_idx('min_col')
    mrp_i = get_idx('mrp_col')
    categ_i = get_idx('categ_col')
    pos_categ_i = get_idx('pos_categ_col')
    bc_i = get_idx('barcode_col')
    brand_i = get_idx('brand_col')
    unit_i = get_idx('unit_col')

    # A renamed column would otherwise import silently as blank (no price, no
    # stock, or -- for the barcode -- no products at all).
    missing = [label for label, idx in (('Name', name_i), ('BARCODE', bc_i), ('SALES PRICE', price_i),
                                        ('COST', cost_i), ('Pieces/Quantity', qty_i)) if idx is None]
    if missing:
        raise SystemExit(f"Tab {tab_name!r} has no column {missing}. Its header is: "
                         f"{[clean(h) for h in rows[0] if h]}. Rename it back or update TABS_CONFIG.")

    products = {}
    notes = []
    skipped = []

    for rnum, row in enumerate(rows[1:], start=2):
        if not any(c is not None and str(c).strip() for c in row):
            continue

        raw_name = clean(row[name_i] if name_i is not None and name_i < len(row) else None)
        if not raw_name:
            continue

        raw_bc = clean(row[bc_i] if bc_i is not None and bc_i < len(row) else None).upper()
        # A product row carries a sheet code; the rest (e.g. paint rows pasted
        # at the bottom of the tab) are skipped -- and listed, not dropped quietly.
        if not raw_bc.startswith('MBAHRIA'):
            skipped.append((rnum, raw_name))
            continue

        raw_size = clean(row[size_i] if size_i is not None and size_i < len(row) else None)
        if raw_size in ('0', '-'):
            raw_size = ''
        size_norm = SIZES_MAP.get(raw_size.lower(), raw_size.title() if raw_size else '')

        raw_brand = clean(row[brand_i] if brand_i is not None and brand_i < len(row) else None)
        brand_norm = BRANDS_MAP.get(raw_brand.lower(), raw_brand.title() if raw_brand else '')

        price, p_unit = parse_numeric_and_unit(row[price_i] if price_i is not None and price_i < len(row) else None)
        cost, c_unit = parse_numeric_and_unit(row[cost_i] if cost_i is not None and cost_i < len(row) else None)
        min_p, _ = parse_numeric_and_unit(row[min_i] if min_i is not None and min_i < len(row) else None)
        mrp_p, _ = parse_numeric_and_unit(row[mrp_i] if mrp_i is not None and mrp_i < len(row) else None)
        raw_qty = row[qty_i] if qty_i is not None and qty_i < len(row) else None
        qty, q_unit = parse_qty(raw_qty)
        if not clean(raw_qty):
            notes.append(f"row {rnum} ({raw_name}): quantity empty -> no stock loaded")
        if price <= 0:
            notes.append(f"row {rnum} ({raw_name}): sales price {clean(row[price_i]) or 'empty'} -> "
                         f"imports at 0, which the till refuses to sell")
        elif cost > price:
            notes.append(f"row {rnum} ({raw_name}): cost {cost:g} above sales price {price:g}")

        # Enforce consistency: min <= price <= mrp
        if price > 0:
            if min_p > price:
                notes.append(f"row {rnum} ({raw_name}): min {min_p:g} > price {price:g} -> dropped min")
                min_p = 0.0
            if mrp_p > 0 and mrp_p < price:
                notes.append(f"row {rnum} ({raw_name}): MRP {mrp_p:g} < price {price:g} -> dropped MRP")
                mrp_p = 0.0
        if min_p > 0 and mrp_p > 0 and min_p > mrp_p:
            notes.append(f"row {rnum} ({raw_name}): min {min_p:g} > MRP {mrp_p:g} -> dropped range")
            min_p = mrp_p = 0.0

        raw_categ = clean(row[categ_i] if categ_i is not None and categ_i < len(row) else None)
        categ_path_list = category_path(raw_categ, cfg['default_categ'])

        raw_pos_categ = clean(row[pos_categ_i] if pos_categ_i is not None and pos_categ_i < len(row) else None)
        pos_categ_name = raw_pos_categ if raw_pos_categ else cfg['default_pos_categ']

        explicit_unit = clean(row[unit_i] if unit_i is not None and unit_i < len(row) else None)
        inferred_unit = explicit_unit or p_unit or c_unit or q_unit or ''

        legacy = slug(raw_name, size_norm, brand_norm)
        key = raw_bc or legacy

        if key in products:
            existing_p = products[key]
            existing_p['pieces'] = (existing_p['pieces'] or 0.0) + (qty or 0.0)
            notes.append(f"row {rnum}: duplicate barcode {key}, merged stock pieces")
            continue

        products[key] = {
            'row': rnum,
            'name': raw_name,
            'size': size_norm,
            'brand': brand_norm,
            'price': price,
            'cost': cost,
            'minimum': min_p,
            'mrp': mrp_p,
            'pieces': qty,
            'categ': categ_path_list,
            'pos_categ': pos_categ_name,
            'unit': inferred_unit,
            'code': raw_bc,
            'legacy': legacy,
            'prefix': cfg['xmlid_prefix'],
        }

    print(f"  Parsed {len(products)} products from tab.", flush=True)
    all_categories_str = sorted({' / '.join(p['categ']) for p in products.values()})
    print(f"  Product Categories ({len(all_categories_str)}): {all_categories_str}", flush=True)
    all_pos_cats_str = sorted({p['pos_categ'] for p in products.values()})
    print(f"  POS Categories: {all_pos_cats_str}", flush=True)
    stock_items = [p for p in products.values() if p['pieces'] > 0]
    total_pieces = sum(p['pieces'] for p in stock_items)
    print(f"  Opening Stock: {len(stock_items)} products with {total_pieces:g} total pieces", flush=True)
    units = sorted({p['unit'] for p in products.values() if p['unit']})
    if units:
        print(f"  Sold by measure: {', '.join(f'{u}: ' + ', '.join(p['name'] for p in products.values() if p['unit'] == u) for u in units)}",
              flush=True)
    for n in notes:
        print(f"    note: {n}", flush=True)
    if skipped:
        print(f"  Skipped {len(skipped)} row(s) without a sheet code (MBAHRIA...): "
              f"rows {skipped[0][0]}-{skipped[-1][0]}, e.g. {', '.join(name for _, name in skipped[:5])}", flush=True)

    # -----------------------------------------------------------------------
    # Match Existing Products
    # -----------------------------------------------------------------------
    prefix = cfg['xmlid_prefix']
    imds = IMD.search([
        ('module', '=', XMLID_MODULE), ('model', '=', 'product.template'),
        ('name', '=like', f'{prefix}\\_%')])
    imported_by_imd = Template.with_context(active_test=False).browse(imds.mapped('res_id')).exists()
    
    # Also find any template with default_code matching sheet
    sheet_codes = [p['code'] for p in products.values() if p['code']]
    by_code_templates = Template.with_context(active_test=False).search([('default_code', 'in', sheet_codes)])
    by_code = {t.default_code.upper(): t for t in by_code_templates}

    matched = {}
    renamed = []
    for key, p in products.items():
        if p['code'] and p['code'] in by_code:
            matched[key] = by_code[p['code']]
            if slug(matched[key].name or '') != slug(p['name']):
                renamed.append((p, matched[key].name))

    new_keys = [k for k in products if k not in matched]
    print(f"  Matching: {len(new_keys)} new, {len(matched)} already exist (will be updated)", flush=True)
    for p, old in renamed:
        print(f"    renamed: row {p['row']} {p['code']}: {old} -> {p['name']}", flush=True)
    # Many renames at once means the codes were renumbered: every price and
    # stock count would land on the wrong product.
    if len(matched) >= 10 and len(renamed) > 0.3 * len(matched):
        raise SystemExit(f"Refusing to import {tab_name!r}: {len(renamed)} of {len(matched)} codes now sit on a "
                         f"differently named product. It looks like the codes were renumbered; put each code "
                         f"back on its own product first.")
    tab_codes = {p['code'] for p in products.values()}
    gone = imported_by_imd.filtered(lambda t: (t.default_code or '').upper() not in tab_codes)
    if gone:
        print(f"  {len(gone)} product(s) imported from this tab earlier are no longer in it (left untouched): "
              f"{', '.join(gone.mapped('name'))}", flush=True)

    if not APPLY:
        for p in list(products.values())[:3]:
            print(f"    e.g. [{p['code']}] {p['name']:32s} {p['size']:10s} price {p['price']:>7g} cost {p['cost']:>7g} pieces {p['pieces']}", flush=True)
        print("  [DRY RUN] No changes committed.", flush=True)
        continue

    # -----------------------------------------------------------------------
    # Write to Database
    # -----------------------------------------------------------------------
    started = time.monotonic()
    print("  Importing into Odoo...", flush=True)

    with env.cr.savepoint():
        to_create = []
        costs = []
        updated = 0
        unchanged = 0
        templates_by_key = {}

        for key, p in products.items():
            pos_cat = get_pos_category(p['pos_categ'])
            cat_rec = get_category(p['categ'])
            brand_id = get_brand(p['brand'])
            uom_rec = get_uom(p['unit'])

            vals = {
                'name': p['name'],
                'pos_retail_size': p['size'] or False,
                'list_price': p['price'],
                'minimum_selling_price': p['minimum'],
                'mrp': p['mrp'],
                'categ_id': cat_rec.id if cat_rec else False,
                'pos_categ_ids': [(6, 0, pos_cat.ids)],
                'pos_retail_branch_ids': [(6, 0, branch.ids)],
                'brand_id': brand_id,
                'type': 'consu',
                'is_storable': True,
                'available_in_pos': True,
                'sale_ok': True,
                'purchase_ok': True,
                'company_id': False,
            }
            if p['code']:
                vals['default_code'] = p['code']

            template = Template.browse(matched[key].id) if key in matched else Template

            if template:
                diff = diff_fields(template, vals)
                if diff:
                    template.write(diff)
                    updated += 1
                else:
                    unchanged += 1
                costs.append((template, p['cost']))
                templates_by_key[key] = template
            else:
                if uom_rec:
                    vals['uom_id'] = uom_rec.id
                to_create.append((key, vals, p['cost']))

        if to_create:
            created_templates = Template.create([v for _k, v, _c in to_create])
            xmlids = []
            for (k, _v, _c), tmpl in zip(to_create, created_templates):
                code_slug = slug(products[k]['code']) or products[k]['legacy']
                xmlids.append({
                    'module': XMLID_MODULE,
                    'name': f"{prefix}_{code_slug}",
                    'model': 'product.template',
                    'res_id': tmpl.id,
                    'noupdate': True
                })
                templates_by_key[k] = tmpl
            IMD.create(xmlids)
            costs += [(tmpl, cost) for (_k, _v, cost), tmpl in zip(to_create, created_templates)]
            print(f"    Created {len(created_templates)} records ({time.monotonic() - started:.1f}s)", flush=True)

        # Cost is company-dependent in Odoo 19: set across all companies
        cost_writes = 0
        for comp in companies:
            cost_groups = {}
            for tmpl, cost_val in costs:
                if abs(tmpl.with_company(comp).standard_price - cost_val) > 0.001:
                    cost_groups.setdefault(cost_val, Template.browse())
                    cost_groups[cost_val] |= tmpl
            for cost_val, tmpls in cost_groups.items():
                tmpls.with_company(comp).write({'standard_price': cost_val})
                cost_writes += len(tmpls)

        # Opening stock in branch warehouse
        wanted_stock = {
            templates_by_key[k]: p['pieces']
            for k, p in products.items()
            if p['pieces'] > 0 and k in templates_by_key
        }

        if FORCE_STOCK:
            stock_to_apply = wanted_stock
        else:
            already_counted = has_stock_history(Template.browse([t.id for t in wanted_stock]), branch)
            stock_to_apply = {t: qty for t, qty in wanted_stock.items() if t not in already_counted}

        applied_stock_count = 0
        applied_stock_qty = 0.0
        if stock_to_apply:
            quant_vals = [{
                'product_id': tmpl.product_variant_id.id,
                'location_id': warehouse.lot_stock_id.id,
                'inventory_quantity': qty,
            } for tmpl, qty in stock_to_apply.items()]
            quants = Quant.with_company(branch).with_context(inventory_mode=True).create(quant_vals)
            quants.action_apply_inventory()
            applied_stock_count = len(stock_to_apply)
            applied_stock_qty = sum(stock_to_apply.values())

        print(f"    Stock: {applied_stock_count} products updated with {applied_stock_qty:g} pieces ({len(wanted_stock) - applied_stock_count} skipped: already inventoried)", flush=True)

    env.cr.commit()

    created_cnt = len(to_create)
    grand_created += created_cnt
    grand_updated += updated
    grand_unchanged += unchanged
    grand_stock_products += applied_stock_count
    grand_stock_pieces += applied_stock_qty

    print(f"  Tab Completed: created {created_cnt}, updated {updated}, unchanged {unchanged}, stock set for {applied_stock_count} products ({applied_stock_qty:g} pieces)", flush=True)

print(f"\n{'=' * 78}", flush=True)
print(f"IMPORT COMPLETE SUMMARY:")
print(f"  Total Products Created:   {grand_created}")
print(f"  Total Products Updated:   {grand_updated}")
print(f"  Total Products Unchanged: {grand_unchanged}")
print(f"  Total Stock Initialized:  {grand_stock_products} products ({grand_stock_pieces:g} pieces)")
print(f"{'=' * 78}", flush=True)
