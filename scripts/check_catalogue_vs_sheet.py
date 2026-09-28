"""Compare every column of the Bahria sheet tabs with what is in Odoo. Read-only.

    venv/Scripts/python.exe odoo/odoo-bin shell -c odoo.conf -d <db> --no-http \
        < custom_addons/pos_retail/scripts/check_catalogue_vs_sheet.py

On the server:
    sudo -u odoo /opt/odoo/venv/bin/python3 /opt/odoo/odoo/odoo-bin shell \
        -c /etc/odoo/odoo.conf -d ostore_live --no-http \
        < /opt/odoo/custom_addons/pos_retail/scripts/check_catalogue_vs_sheet.py

For each coded row (MBAHRIA...) of Bahria Paints, POLISH, Chemicals and
Electric: is the product in Odoo, and do its name, barcode, brand, size,
prices, cost, category, till section, branch and stock match the sheet?
Brand, size and category are checked for presence (the importers tidy their
spelling). A price range the importers dropped because it contradicts the
sales price is counted separately, as is stock that moved since the count.
Every product with nothing in hand is listed with the reason (quantity empty
in the sheet, 0 in the sheet, not loaded yet, or sold since the count).

Optional: IMPORT_XLSX (local file instead of the Google Sheet), IMPORT_BRANCH.
"""

import datetime
import io
import os
import re
import urllib.request

import openpyxl

SHEET_URL = ('https://docs.google.com/spreadsheets/d/'
             '1wyP6KnQO5LowvsHZoHM4rntFwyJA8Wc5Kc652SXJDtI/export?format=xlsx')
XLSX = os.environ.get('IMPORT_XLSX', SHEET_URL)
BRANCH = os.environ.get('IMPORT_BRANCH', 'Bahria')
TABS = ['Bahria Paints', 'Bahria POLISH', 'Bahria Chemicals', 'Bahria Electric']
COLUMNS = {
    'name': ['name'], 'size': ['size', 'amp/watt/volt'], 'brand': ['brand'],
    'qty': ['quantity', 'pieces'], 'cost': ['cost'], 'price': ['sales price'],
    'min': ['minimum selling price'], 'mrp': ['maximum retail price (mrp)'],
    'categ': ['product category'], 'code': ['barcode'],
}


def clean(value):
    if value is None:
        return ''
    if isinstance(value, datetime.datetime):
        return f"{value.month}/{value.day}"
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    return re.sub(r'\s+', ' ', str(value)).strip()


def number(value):
    if isinstance(value, (int, float)):
        return float(value)
    match = re.search(r'\d+(?:\.\d+)?', clean(value))
    return float(match.group(0)) if match else None


if XLSX.startswith('http'):
    with urllib.request.urlopen(XLSX, timeout=120) as response:
        source = io.BytesIO(response.read())
else:
    source = XLSX
wb = openpyxl.load_workbook(source, read_only=True, data_only=True)

branch = env['res.company'].sudo().search([('name', 'ilike', BRANCH), ('child_ids', '=', False)])
if len(branch) != 1:
    raise SystemExit(f"Expected one branch matching {BRANCH!r}, found {branch.mapped('name')}")
warehouse = env['stock.warehouse'].sudo().search([('company_id', '=', branch.id)], limit=1)
Product = env['product.product'].sudo().with_context(active_test=False)
goods = env.ref('product.product_category_goods', raise_if_not_found=False)

print()
print("=" * 78)
print(f"SHEET vs ODOO   (read-only)   branch: {branch.name}")
print("=" * 78)
for tab in TABS:
    if tab not in wb.sheetnames:
        print(f"\n{tab}: not in the sheet")
        continue
    rows = list(wb[tab].iter_rows(values_only=True))
    header = [clean(h).lower() for h in rows[0]]
    idx = {key: next((header.index(a) for a in aliases if a in header), None) for key, aliases in COLUMNS.items()}
    checks = {}

    def check(label, ok, detail=''):
        entry = checks.setdefault(label, [0, []])
        if ok:
            entry[0] += 1
        else:
            entry[1].append(detail)

    coded = 0
    out_of_stock = []
    for rownum, row in enumerate(rows[1:], start=2):
        get = lambda key: row[idx[key]] if idx[key] is not None and idx[key] < len(row) else None
        code = clean(get('code')).upper()
        if not code.startswith('MBAHRIA'):
            continue
        coded += 1
        name = clean(get('name'))
        where = f"row {rownum} {code} {name}"
        product = Product.search([('default_code', '=', code)], limit=1)
        check('in Odoo', bool(product), where)
        if not product:
            continue
        t = product.product_tmpl_id
        check('name', clean(t.name) == name, f"{where}: Odoo has {t.name!r}")
        check('barcode', product.barcode == code, f"{where}: Odoo barcode {product.barcode}")
        if clean(get('brand')):
            check('brand', bool(t.brand_id), f"{where}: sheet {clean(get('brand'))!r}, Odoo none")
        if clean(get('size')) not in ('', '0'):
            check('size', bool(t.pos_retail_size), f"{where}: sheet {clean(get('size'))!r}, Odoo none")
        price, cost = number(get('price')) or 0.0, number(get('cost')) or 0.0
        check('sales price', abs(t.list_price - price) < 0.01, f"{where}: sheet {price:g}, Odoo {t.list_price:g}")
        check('cost', abs(t.with_company(branch).standard_price - cost) < 0.01,
              f"{where}: sheet {cost:g}, Odoo {t.with_company(branch).standard_price:g}")
        low, high = number(get('min')) or 0.0, number(get('mrp')) or 0.0
        conflict = price and ((low and low > price) or (high and high < price)) or (low and high and low > high)
        if conflict:
            check('min / MRP (dropped: contradicts price)', False, f"{where}: {low:g}-{high:g} vs price {price:g}")
        else:
            check('min / MRP', abs(t.minimum_selling_price - low) < 0.01 and abs(t.mrp - high) < 0.01,
                  f"{where}: sheet {low:g}-{high:g}, Odoo {t.minimum_selling_price:g}-{t.mrp:g}")
        check('category', bool(t.categ_id) and t.categ_id != goods, f"{where}: Odoo {t.categ_id.complete_name}")
        check('till section', bool(t.pos_categ_ids), where)
        check('sold at branch only', t.pos_retail_branch_ids == branch,
              f"{where}: {t.pos_retail_branch_ids.mapped('name') or 'every branch'}")
        qty = number(get('qty'))
        on_hand = product.with_company(branch).with_context(warehouse_id=warehouse.id).qty_available
        if qty is not None:
            check('stock = sheet quantity', abs(on_hand - qty) < 0.001,
                  f"{where}: sheet {qty:g}, on hand {on_hand:g}")
        if on_hand <= 0:
            if qty is None:
                reason = "QUANTITY is empty in the sheet -> fill it in, then re-run the import"
            elif qty <= 0:
                reason = f"the sheet says {qty:g}"
            elif not env['stock.move'].sudo().search_count([
                    ('product_id', '=', product.id), ('company_id', '=', branch.id),
                    ('is_inventory', '=', True), ('state', '=', 'done')]):
                reason = f"sheet says {qty:g} but it was never loaded -> re-run the import"
            else:
                reason = f"sheet says {qty:g}; loaded, then sold or adjusted down since"
            out_of_stock.append(f"row {rownum} {code} {name} (on hand {on_hand:g}): {reason}")

    print(f"\n{tab}: {coded} products in the sheet")
    for label, (ok, problems) in checks.items():
        status = "all OK" if not problems else f"{len(problems)} not matching"
        print(f"  {label:42s} {ok:4d} OK   {status}")
        for detail in problems[:5]:
            print(f"      - {detail}")
        if len(problems) > 5:
            print(f"      ... and {len(problems) - 5} more")
    # Every one, not just five: this is the list someone works through.
    print(f"  out of stock at the till: {len(out_of_stock)}")
    for line in out_of_stock:
        print(f"      - {line}")
print()
print("Stock can differ once the till has sold or received something since the count.")
print("=" * 78)
