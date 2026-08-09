"""Import-template definitions and workbook builder.

Lives inside the addon (not in scripts/) because the workbooks are now generated
per download by controllers/import_template.py, against the database the user is
importing into. That is what lets every name-matched column carry a dropdown of
values that actually exist -- see tools/live_values.py.

HEADERS ARE THE FIELD'S ODOO LABEL, NOT ITS TECHNICAL NAME. A shop owner has to
be able to read the sheet: "Sales Price" tells them something, `list_price` does
not. Odoo's importer matches a header against the label as well as the technical
name, so this costs nothing at import time -- but the label must be EXACT,
character for character, or the column silently arrives unmapped. Worse, a
near-miss can match the WRONG field. Anything changed here must be re-checked by
dry-running the file through base_import and asserting the resolved field per
column.

Four layers of explanation, because a spreadsheet has no room for prose:
  * dropdown       -> the values that exist, so nothing has to be typed
  * click a cell   -> Excel input message, the one-line brief
  * hover the head -> cell comment, the full explanation
  * READ ME FIRST  -> every field in a table, plus the colour key and the order
Abbreviations are spelled out on first use (Maximum Retail Price (MRP), Unit of
Measure (UoM), Stock Keeping Unit (SKU), Point of Sale (POS)): the shop owners
using these files are not Odoo people.
"""
import io

import xlsxwriter

from . import live_values

# Rows the dropdowns, tooltips, red flags and self-filling External ID cover.
# Not a soft limit: a row BEYOND this has no External ID, so it imports as a new
# product on every upload and duplicates the catalogue on the second one. Sized
# for a real hardware shop rather than for a tidy number.
MAX_ROW = 5000

# Excel's own hard limits on a data-validation input message.
TITLE_MAX, MSG_MAX = 32, 255

VALUES_SHEET = "Valid Values"

# Spelled out rather than written inline. Every time a backslash escape in this
# file has gone through a shell heredoc it has come back as a real newline and
# broken the module; a named constant cannot be mangled that way.
NEWLINE = chr(10)

GROUPS = {
    "What it is":        "#2F5597",
    "How it is filed":   "#1F7A6B",
    "How it is sold":    "#0F6E8C",
    "What it costs":     "#2E7D32",
    "Price limits":      "#B7791F",
    "Tax & where sold":  "#6B3FA0",
    "Supplier & extras": "#5A5A5A",
}

GROUP_BLURB = {
    "What it is": "Naming and identifying the product.",
    "How it is filed": "Where it sits in your catalogue: categories, brand, unit of measure.",
    "How it is sold": "Whether the till asks for whole pieces or a measured amount, "
                      "and which shortcut buttons it offers.",
    "What it costs": "The shelf price and what you paid for it.",
    "Price limits": "The range a cashier may sell inside without manager approval.",
    "Tax & where sold": "Tax, and which parts of Odoo the product shows up in.",
    "Supplier & extras": "Who supplies it, plus optional details.",
}

MONEY_HEADERS = {
    "Sales Price", "Cost", "Minimum Selling Price",
    "Maximum Retail Price (MRP)", "Wholesale Price",
}

# Fixed value sets become dropdowns: the user picks instead of guessing, and a
# typo cannot reach the importer. Keyed by technical field name.
CHOICES = {
    "type": ["Goods", "Service", "Combo"],
    "available_in_pos": ["TRUE", "FALSE"],
    "sale_ok": ["TRUE", "FALSE"],
    "purchase_ok": ["TRUE", "FALSE"],
    "is_storable": ["TRUE", "FALSE"],
}

def _external_id_column(what):
    """The self-filling id column, shared by every template.

    Present on all of them now. It used to be on the product sheet alone, which
    meant correcting a mistake in any OTHER sheet and re-sending it added
    everything a second time.
    """
    return ("External ID", "id", "Supplier & extras", False,
            "Fills itself. Do not type here.",
            "Fills itself from the columns that identify the row; you never type "
            "in this column. It is what lets you FIX A MISTAKE AND SEND THE SAME "
            "FILE AGAIN: rows Odoo has already seen are updated in place rather "
            "than added a second time. If the whole column is empty and red, "
            "your spreadsheet did not run the formula (LibreOffice and WPS need "
            "Tools > Options > Calc > Formula > Recalculation on File Load > "
            "Always). Uploading like that still works, but a re-upload will "
            "duplicate your %s." % what,
            "", "", "")


# (header = exact Odoo label, technical field, group, required, brief, full help, ex1, ex2, ex3)
PRODUCT_COLUMNS = [
    ("Name", "name", "What it is", True,
     "The product name as you want it printed on the receipt.",
     "What the product is called, as it will appear at the till and on the "
     "receipt. This is the only column you cannot leave blank.",
     "Nestle Water 1.5L", "Lays Classic Chips", "Refined Sugar (per Kg)"),
    ("Internal Reference", "default_code", "What it is", False,
     "Your own short code for the item, also called a Stock Keeping Unit (SKU).",
     "Your own short code for the item, also known as a Stock Keeping Unit "
     "(SKU). It is for your staff, not the customer. Leave blank if you do not "
     "use codes.",
     "BEV-W15", "SNK-LAY", "GRC-SUG"),
    ("Barcode", "barcode", "What it is", False,
     "The number under the barcode on the pack. Must not repeat.",
     "The number printed under the barcode on the pack, used for scanning at "
     "the till. It must be unique: two products cannot share one barcode.",
     "8964000221013", "8964000112045", ""),
    ("Image", "image_1920", "What it is", False,
     "A web address (https://...) to the photo. Odoo downloads it.",
     "A picture for the till screen. Paste the WEB ADDRESS of the image: "
     "right-click the supplier's photo, Copy Image Address, paste it here. Odoo "
     "downloads it during the import and keeps its own copy. The address must "
     "be reachable from the computer running Odoo and start with http:// or "
     "https://. A file on your own hard disk cannot be used this way.",
     "", "", ""),
    ("Product Category", "categ_id", "How it is filed", False,
     "Accounting/stock category. Use the FULL path, e.g. Goods / Beverages.",
     "The accounting and stock category, used for reporting and inventory "
     "valuation. Categories are nested, so write the full path exactly as it "
     "appears in Inventory > Configuration > Product Categories ('Goods / "
     "Beverages', not just 'Beverages'). Import your categories BEFORE your "
     "products. Leave blank to use the company default.",
     "", "", ""),
    ("Point of Sale Category", "pos_categ_ids", "How it is filed", False,
     "The button group on the till screen. Commas, NO SPACE after them.",
     "Which button group the item sits under on the Point of Sale (POS) till "
     "screen. This is a different list from Product Category. For several, "
     "separate them with commas and NO SPACE after the comma "
     "(\"Snacks,Beverages\", not \"Snacks, Beverages\"): Odoo does not trim "
     "the space and would look for a category called \" Beverages\". Import "
     "your till categories BEFORE your products.",
     "", "", ""),
    ("Brand", "brand_id", "How it is filed", False,
     "Maker or brand, e.g. Nestle. Blank for unbranded goods.",
     "The maker or brand the item is sold under, e.g. Nestle or Tapal. Used to "
     "group and filter the catalogue. Leave blank for loose or unbranded goods.",
     "", "", ""),
    ("Unit", "uom_id", "How it is filed", False,
     "Unit of Measure (UoM): how you count it. Units, kg, Litre.",
     "The Unit of Measure (UoM), meaning how the item is counted and sold: "
     "Units for anything you sell one at a time, kg for anything weighed, Litre "
     "for liquids. Must match a name in Inventory > Configuration > Units "
     "exactly. Defaults to Units when blank. This one column decides how the "
     "till asks for a quantity: set it to kg or m and the cashier gets a "
     "decimal keypad with shortcut buttons instead of a plus/minus stepper.",
     # Row 3 is kg on purpose. It is the row carrying fractional Quick
     # Quantities and kg-based Packagings, and those are only valid on a
     # product measured by weight -- leaving it as "Units" made the shipped
     # template fail on its own example data.
     "Units", "Units", "kg"),
    ("Quick Quantities", "pos_retail_quick_qty", "How it is sold", False,
     "Shortcut buttons at the till. BLANK MEANS NONE, not defaults.",
     "The shortcut buttons the till offers for this item, e.g. "
     "\"0.5, 1, 2, 5, 10\". Every value must be a positive number, and an item "
     "sold by the piece cannot have fractional shortcuts. WARNING: because this "
     "column exists in the sheet, leaving a cell empty sets NO shortcut buttons "
     "for that product. It does not fall back to the defaults. To get the "
     "defaults for a product, delete this whole column from your file.",
     # Whole numbers on the two Units rows and fractions only on the kg row:
     # a fractional shortcut on a piece product is rejected on save, so mixing
     # them up here would ship a template that fails on its own example data.
     "1, 6, 12", "1, 5, 10", "0.5, 1, 5, 10, 25"),
    ("Packagings", "uom_ids", "How it is sold", False,
     "Other units it may be sold in. Commas, NO SPACE after them.",
     "Extra units this item may also be sold in. Each must measure the same "
     "thing as the base Unit; Odoo converts back to it, so stock stays "
     "correct. For several, separate them with commas and NO SPACE after the "
     "comma (\"Roll of 100 m,Bundle of 50 m\"): Odoo does not trim the space "
     "and would look for a unit called \" Bundle of 50 m\". For a pack that "
     "needs its own barcode and price, use the Product Package import "
     "(STEP 5) instead.",
     # Each example matches its row's Unit: a Pack of 6 for a product counted in
     # Units, kg-based sacks for one measured in kg. A length unit on a Units
     # product would convert to nothing and is the classic way to break stock.
     "", "", ""),
    ("Sales Price", "list_price", "What it costs", True,
     "The normal shelf price your customer pays.",
     "The normal shelf price your customer pays, before any discount or "
     "pricelist. Enter numbers only, no currency symbol.",
     120, 50, 250),
    ("Cost", "standard_price", "What it costs", False,
     "What YOU pay your supplier for one unit.",
     "What you pay your supplier for one unit. This is not shown to customers; "
     "it is what drives every profit and margin figure in the reports.",
     95, 38, 210),
    ("Minimum Selling Price", "minimum_selling_price", "Price limits", False,
     "Lowest price allowed without a manager PIN. 0 = no limit.",
     "The lowest price a cashier may sell at without a manager Personal "
     "Identification Number (PIN). Put 0 for no lower limit. It must not be "
     "above the Sales Price or the product will not save.",
     110, 45, 230),
    ("Maximum Retail Price (MRP)", "mrp", "Price limits", False,
     "Maximum Retail Price: highest price allowed. Usually printed on the pack.",
     "Maximum Retail Price: the highest price a cashier may sell at without a "
     "manager Personal Identification Number (PIN). This is usually the price "
     "printed on the pack by the manufacturer. Put 0 for no upper limit. It "
     "must not be below the Sales Price or the product will not save.",
     130, 55, 275),
    ("Wholesale Price", "wholesale_price", "Price limits", False,
     "Reference only. Does NOT make anyone pay this price.",
     "The price you would offer a bulk buyer. For your reference only: filling "
     "this in does NOT make anyone pay it. To actually sell at this price, set "
     "up the Wholesale pricelist and assign it to the customer.",
     105, 42, 225),
    ("Sales Taxes", "taxes_id", "Tax & where sold", False,
     "Best left blank: the product picks up the company default tax.",
     "The tax added when you sell this item. Best left blank so the product "
     "picks up the company default. If you do fill it in, copy the exact tax "
     "name from Accounting > Configuration > Taxes; a sales tax and a purchase "
     "tax can share a name (both '15%'), and an ambiguous name makes the "
     "import guess which one you meant. For several taxes, separate them with "
     "commas and NO SPACE after the comma.",
     "", "", ""),
    ("Available in POS", "available_in_pos", "Tax & where sold", False,
     "TRUE shows it at the till. FALSE hides it from cashiers.",
     "TRUE puts the product on the Point of Sale (POS) till screen. Leave blank "
     "or FALSE and the cashier will never see it, even though it exists in the "
     "catalogue.",
     "TRUE", "TRUE", "TRUE"),
    ("Sales", "sale_ok", "Tax & where sold", False,
     "Means 'can be sold'. TRUE allows it on quotations and invoices.",
     "Odoo's own name for 'can be sold'. TRUE allows the item to be added to "
     "quotations and customer invoices. This is separate from Available in POS: "
     "an item can be sellable on paper but hidden at the till.",
     "TRUE", "TRUE", "TRUE"),
    ("Purchase", "purchase_ok", "Tax & where sold", False,
     "Means 'can be bought'. TRUE allows it on purchase orders.",
     "Odoo's own name for 'can be bought'. TRUE allows the item to be added to "
     "purchase orders you send to your vendors.",
     "TRUE", "TRUE", "TRUE"),
    ("Track Inventory", "is_storable", "Tax & where sold", False,
     "TRUE for goods you count in stock. FALSE for services.",
     "TRUE for physical goods whose quantity you want counted and warned about "
     "when it runs low. FALSE for services and anything you do not keep a "
     "stock figure for.",
     "TRUE", "TRUE", "TRUE"),
    ("Product Type", "type", "Tax & where sold", False,
     "Goods, Service or Combo. Almost always Goods.",
     "Goods for anything physical, Service for labour or fees, Combo for a "
     "bundle made of other products. For a retail shop this is almost always "
     "Goods. Defaults to Goods when blank.",
     "Goods", "Goods", "Goods"),
    ("Vendors / Vendor", "seller_ids/partner_id", "Supplier & extras", False,
     "Who you buy it from. The contact must already exist.",
     "Who you buy this item from. The contact must already exist as a vendor "
     "in Customers & Vendors. The heading has two parts because it reaches "
     "through to the vendor line stored on the product.",
     "", "", ""),
    ("Weight", "weight", "Supplier & extras", False,
     "In kilograms. Only needed for delivery charged by weight.",
     "The weight of one unit, in kilograms. Only needed if you charge delivery "
     "by weight. Leave blank otherwise.",
     1.5, 0.05, 1),
    ("Sales Description", "description_sale", "Supplier & extras", False,
     "Optional note shown to the customer on quotations and invoices.",
     "An optional line shown to the customer on quotations and invoices. Leave "
     "blank unless the item needs explaining.",
     "", "", ""),
    _external_id_column("products"),
]

ESSENTIAL_FIRST = [
    "name", "default_code", "barcode", "categ_id", "pos_categ_ids",
    "list_price", "standard_price", "mrp", "available_in_pos",
]

PRODUCT_CATEGORY_COLUMNS = [
    ("Name", "name", "What it is", True,
     "The category name ALONE, without the parent path.",
     "The category on its own, WITHOUT the parent path. Write 'Beverages', not "
     "'Goods / Beverages'; the parent goes in the next column.",
     "Cleaning", "Detergents", "Stationery"),
    ("Parent Category", "parent_id", "How it is filed", False,
     "Full path of the category above this one. Blank = top level.",
     "The category this one sits under, written as its full path. Leave blank "
     "for a top-level category. A parent created earlier in this same file "
     "counts, which is why row 2 can sit under the category row 1 creates: "
     "always list parents ABOVE their children. Importing a name that already "
     "exists creates a SECOND category with that name, so check the list first.",
     "Goods", "Goods / Cleaning", "Goods"),
    _external_id_column("categories"),
]

POS_CATEGORY_COLUMNS = [
    ("Category Name", "name", "What it is", True,
     "The name printed on the category button at the till.",
     "The name printed on the category button at the Point of Sale (POS) till "
     "screen. Importing a name that already exists creates a SECOND button "
     "with that name, so check the list first.",
     "Household", "Stationery", "Frozen"),
    ("Parent Category", "parent_id", "How it is filed", False,
     "Blank for a top-level button. List parents above their children.",
     "Leave blank for a top-level button. Use it only if you want a second "
     "level of buttons underneath another. List parents ABOVE their children "
     "in this file.",
     "", "", ""),
    ("Sequence", "sequence", "How it is filed", False,
     "Display order: lower numbers appear first. Use gaps of 10.",
     "Odoo's name for display order: lower numbers appear first on the till "
     "screen. Leave blank and Odoo orders by name. Use gaps of 10 so you can "
     "slot new categories in between later without renumbering everything.",
     10, 20, 30),
    ("Color", "color", "Supplier & extras", False,
     "A number 0-11 picking a preset button colour. Blank = default.",
     "A number from 0 to 11 picking one of Odoo's preset button colours. Leave "
     "blank for the default.",
     "", "", ""),
    _external_id_column("till sections"),
]

POS_PACKAGE_COLUMNS = [
    ("Product", "product_id", "What it is", True,
     "The product this pack contains. It must already exist.",
     "The item this package holds. It must already exist, so import your "
     "products first. Stock is still counted on the product itself: every pack "
     "size you sell draws down the same quantity.",
     "", "", ""),
    ("Unit", "uom_id", "How it is filed", True,
     "The pack size, e.g. 5 kg Bag or Box of 10. Must measure the same thing "
     "as the product's own unit.",
     "The Unit of Measure (UoM) that defines how much this pack holds, e.g. "
     "'5 kg Bag' or 'Box of 10'. It must measure the same thing as the "
     "product's own unit: a product stocked in kg can have a 5 kg Bag pack, "
     "but not a Box of 10. The quantity per pack is worked out from this "
     "automatically, which is why there is no quantity column.",
     "", "", ""),
    ("Package Name", "package_name", "What it is", False,
     "Optional label shown at the till. Blank uses the unit's name.",
     "An optional label for the pack, shown at the till and on the receipt. "
     "Leave blank and the unit's own name is used.",
     "", "", ""),
    ("Barcode", "barcode", "What it is", False,
     "The pack's own barcode. Scanning it sells one whole pack.",
     "The barcode printed on the pack itself, which is different from the "
     "product's own barcode. Scanning it at the till sells one whole pack.",
     "", "", ""),
    ("Product Code (SKU)", "sku", "What it is", False,
     "Your own code for this pack, separate from the product's.",
     "Your own short code for this pack, independent of the product's own "
     "Stock Keeping Unit (SKU).",
     "", "", ""),
    ("Selling Price", "list_price", "What it costs", False,
     "Price for one whole pack. 0 = product price x pack quantity.",
     "The price of one whole pack. Leave at 0 and the till charges the "
     "product's own price multiplied by how much the pack holds, which is "
     "usually what you want unless the pack is discounted.",
     "", "", ""),
    ("Cost Price", "standard_price", "What it costs", False,
     "What one whole pack costs you.",
     "What one whole pack costs you from your supplier. Drives the pack's "
     "margin figures.",
     "", "", ""),
    ("Minimum Price", "min_price", "Price limits", False,
     "Lowest price this pack may be sold at. 0 = no limit.",
     "The lowest price this pack may be sold at. Zero means no limit. Works "
     "the same way as the product's Minimum Selling Price, but for the pack.",
     "", "", ""),
    ("Maximum Price", "max_price", "Price limits", False,
     "Highest price this pack may be sold at. 0 = no limit.",
     "The highest price this pack may be sold at, e.g. the Maximum Retail "
     "Price printed on the sack. Zero means no limit.",
     "", "", ""),
    _external_id_column("packs"),
]

UOM_COLUMNS = [
    ("Unit Name", "name", "What it is", True,
     "What the unit is called, e.g. Roll of 75 m. Include the size.",
     "What the unit is called. INCLUDE THE SIZE: a unit's conversion factor is "
     "global, shared by every product, so a bare \"Roll\" cannot exist (one "
     "product's roll is 100 m and another's is 50 m, and one factor cannot be "
     "both). Name it \"Roll of 75 m\". For a pack size unique to a single "
     "product, skip this file and use the Product Package import instead.",
     "Roll of 75 m", "Coil of 30 m", "Crate of 12"),
    ("Reference Unit", "relative_uom_id", "How it is filed", True,
     "The unit this one is built from, e.g. m. Must already exist.",
     "The existing unit this one is measured in. It fixes what kind of thing "
     "the new unit measures: build it on m and it is a length, on kg a weight, "
     "on Units a count. Two units can only convert if they trace back to the "
     "same root, which is what makes selling a length in kilos impossible.",
     "m", "m", "Units"),
    ("Contains", "relative_factor", "How it is sold", True,
     "How many Reference Units are in one of these. 75 for a 75 m roll.",
     "How many of the Reference Unit make up one of these. A \"Roll of 75 m\" "
     "built on m contains 75. A \"Crate of 12\" built on Units contains 12. "
     "Odoo uses this for every conversion, so an error here silently misstates "
     "stock on every sale of the unit.",
     75, 30, 12),
    _external_id_column("units"),
]

# The order that stops a first-time setup failing. Repeated on every template,
# because whichever file the user opens first is the one they read.
STEPS = (
    "THE ORDER MATTERS. Import in this order, because each step is matched by "
    "name against what the step before it created:\n"
    "    STEP 1  Units of Measure    (Inventory > Configuration > Units of Measure)\n"
    "    STEP 2  Product Categories  (Inventory > Configuration > Product Categories)\n"
    "    STEP 3  Till Categories     (Point of Sale > Configuration > Categories)\n"
    "    STEP 4  Products            (Point of Sale > Products)\n"
    "    STEP 5  Product Packages    (Point of Sale > Products > Product Packages)\n"
    "STEP 1 is only needed for a size Odoo does not already have, and STEP 5 only\n"
    "if you sell the same item in more than one pack size. Import products before\n"
    "their categories and every category cell fails with \"No matching record found\"."
)


def essentials_first(columns):
    by_field = {c[1]: c for c in columns}
    ordered = [by_field[f] for f in ESSENTIAL_FIRST if f in by_field]
    ordered += [c for c in columns if c[1] not in set(ESSENTIAL_FIRST)]
    return ordered


def intro(what, where, extra=""):
    return (
        f"Fill one row per {what} on the Products sheet, delete the three example rows, then "
        f"save and upload the file with the Import button on {where}.\n\n"
        "CLICK any cell to see a one-line note on what belongs there. HOVER a heading for the "
        "full explanation. Headings are coloured by what they are about (key below), and a "
        "heavy red outline means the column must be filled in. Some columns are dropdowns: "
        "pick a value instead of typing it.\n\n"
        "Do not rename or reorder the heading row: Odoo matches your columns by those exact "
        "words. Anything matched by name (categories, brands, units, taxes, vendors) must "
        "already exist, or tick 'create missing values' on the import screen."
        + (f"\n\n{extra}" if extra else "")
    )


# ---------------------------------------------------------------------------
# The five-column sheet: the default product template.
#
# Everything removed from here is removed because it costs the shopkeeper a
# decision or a lookup, and every one of them has a cheaper home:
#
#   Unit             omitted, NOT blanked. uom_id is required=True but carries a
#                    default of Units, so leaving the column out is safe while a
#                    blank cell in a present column writes False and fails.
#   Product Category no default in Odoo 19 at all, so it is supplied by a field
#                    default in models/product_template.py instead of being
#                    typed 500 times.
#   Till Category,   set after import, in one gesture per group, on the Finish
#   Available in POS Product Setup list. Ticking 500 boxes in a spreadsheet and
#                    ticking one box over 500 selected rows are not the same job.
#   Min/MRP/         omitted so _check_selling_price_range cannot reject a row
#   Wholesale        during a bulk load.
#   Quick Quantities omitted so the blank-cell-wipes-the-default trap cannot
#                    fire (see the warning that had to be written into its help).
#   Packagings,      omitted so the comma-with-no-space rule disappears entirely.
#   Taxes, POS cat
#
# What is left is five columns of plain typing with no name matching anywhere,
# which also means none of the other templates are prerequisites any more.
# ---------------------------------------------------------------------------
# Exactly ONE example row, and every value in it is plain typing: no category,
# no unit, no brand, nothing that has to already exist. That matters twice over.
# It works on a brand new shop's database, where the old examples ("Goods /
# Beverages", "Nestle", "Karachi Beverages Distributors") were nine guaranteed
# errors on the very first download. And it keeps the file previewable: a sheet
# with headers but no data rows makes Odoo's parse_preview raise "list index out
# of range", because it reads a row to show you and there is none.
PRODUCT_SIMPLE_COLUMNS = [
    ("Name", "name", "What it is", True,
     "What the item is called. The only column you have to think about.",
     "What the item is called, exactly as you want it to read on the receipt, "
     "e.g. \"PVC Pipe 1 inch\" or \"Brass Bib Cock 1/2 inch\". Include the size "
     "in the name: each size is its own product.",
     "PVC Pipe 1 inch", "", ""),
    ("Sales Price", "list_price", "What it costs", True,
     "What the customer pays. Numbers only, no Rs.",
     "What you charge the customer for one of them. Numbers only, no currency "
     "symbol and no commas.",
     200, "", ""),
    ("Cost", "standard_price", "What it costs", False,
     "What you paid your supplier. Numbers only.",
     "What you pay your supplier for one of them. Optional, but without it the "
     "profit and margin figures stay empty. Numbers only.",
     150, "", ""),
    ("Barcode", "barcode", "What it is", False,
     "The number under the barcode. Leave blank for loose fittings.",
     "The number printed under the barcode on the pack, if it has one. Leave it "
     "blank for loose fittings and anything sold from a bin. No two products "
     "may share a barcode.",
     "", "", ""),
    ("Image", "image_1920", "What it is", False,
     "A web address (https://...) to the photo. Odoo downloads it.",
     "A picture for the till screen. Paste the WEB ADDRESS of the image, e.g. "
     "the one your supplier shows on their website: right-click the picture, "
     "Copy Image Address, paste it here. Odoo downloads it during the import "
     "and stores its own copy, so the address does not have to keep working "
     "afterwards. The address must be reachable from the computer running "
     "Odoo, and start with http:// or https://. A photo on your own hard disk "
     "cannot be used this way; add those on the product form. Leave blank for "
     "no picture.",
     "", "", ""),
    ("Unit", "uom_id", "How it is sold", False,
     "How you sell it: Units, kg, m, ft2, L. Blank means Units.",
     "How the item is counted and sold. Units for anything sold one at a time, "
     "kg for anything WEIGHED, m or ft for anything cut to length, L for "
     "liquids, ft2 for tiles. Pick from the dropdown. Leave blank and it "
     "becomes Units. This one column also decides how the till asks for the "
     "quantity: set kg or m and the cashier gets a decimal keypad with shortcut "
     "buttons instead of a plus/minus counter.",
     "m", "", ""),
    ("Minimum Selling Price", "minimum_selling_price", "Price limits", False,
     "Lowest price allowed without a manager PIN. Blank or 0 = no limit.",
     "The lowest price a cashier may sell this at without a manager Personal "
     "Identification Number (PIN). Leave blank or put 0 for no lower limit. It "
     "must not be higher than the Sales Price or the row will be refused.",
     180, "", ""),
    ("Maximum Retail Price (MRP)", "mrp", "Price limits", False,
     "Highest price allowed, usually printed on the pack. Blank or 0 = none.",
     "Maximum Retail Price: the highest a cashier may sell at without a manager "
     "Personal Identification Number (PIN), usually the price printed on the "
     "pack. Leave blank or put 0 for no upper limit. It must not be lower than "
     "the Sales Price or the row will be refused.",
     220, "", ""),
    ("Vendors / Vendor", "seller_ids/partner_id", "Supplier & extras", False,
     "Who you buy it from. Import your suppliers first.",
     "The supplier you buy this item from. The supplier must already exist, so "
     "load the Supplier List sheet before this one. Pick from the dropdown. "
     "Leave blank if you buy it from several places or have not recorded them "
     "yet.",
     "", "", ""),
    ("Weight", "weight", "Supplier & extras", False,
     "Shipping weight in kg. NOT how you sell it - that is the Unit column.",
     "The weight of ONE unit, in kilograms, used only for delivery charges and "
     "labels. This is NOT how you sell the item: to sell something BY weight, "
     "set the Unit column to kg and leave this blank. A 50 kg cement bag sold "
     "as one bag has Unit = Units and Weight = 50; cement sold loose by the "
     "kilo has Unit = kg and Weight blank.",
     "", "", ""),
    ("External ID", "id", "Supplier & extras", False,
     "Fills itself. Do not type here.",
     "Fills itself from the Name; you never type in this column. It is what "
     "lets you FIX A MISTAKE AND SEND THE SAME FILE AGAIN: rows Odoo has "
     "already seen are updated in place instead of being added a second time. "
     "If you clear it, re-uploading will create duplicates.",
     "", "", ""),
]

# Excel builds the External ID from the Name, so the shopkeeper never sees it as
# work. Kept deliberately simple: lower-case, spaces to underscores, dots to
# dashes. Anything Odoo would reject in an external id is not produced by it.
def _slug(col, row):
    return ('SUBSTITUTE(SUBSTITUTE(SUBSTITUTE(LOWER(TRIM($%s%d))'
            '," ","_"),".","-"),"/","-")' % (col, row))


def external_id_formula(row, cols):
    """Build the self-filling External ID for one row.

    Derived from the columns that actually make the record unique. A package
    keyed on its product alone would give every pack size of that product the
    same id, so the second one would overwrite the first on import; a category
    keyed on its name alone would merge "Goods / Cleaning" with any other
    "Cleaning". Hence a list of columns rather than always column A.
    """
    body = '&"_"&'.join(_slug(c, row) for c in cols)
    return '=IF($%s%d="","","p_"&%s)' % (cols[0], row, body)

# Worked examples live on READ ME FIRST as a picture, not as rows in the sheet.
# Rows have to be deleted, and a row that is not deleted becomes a junk product;
# a picture cannot be imported by accident.
# A picture of a filled sheet, printed on READ ME FIRST rather than left as rows
# in the file. Rows have to be deleted and the ones that are not become junk
# products; a picture cannot be imported by accident.
#
# Chosen to cover every kind of item a hardware shop actually stocks, because
# the hard part is not typing a name, it is knowing what to put in Unit:
#   cut to length, sold whole by the piece, weighed loose, sold by area,
#   and a bagged item that is one piece but has a shipping weight.
# (Name, Sales Price, Cost, Barcode, Unit, Min, MRP, Weight, why)
SIMPLE_WORKED_EXAMPLE = [
    ("PVC Pipe 1 inch", "20", "14", "", "ft", "18", "22", "",
     "Cut to length. Priced PER FOOT, so Unit is ft and the till lets the "
     "cashier key 2.75."),
    ("Brass Bib Cock 1/2 inch", "850", "600", "8964000111222", "", "780", "900", "",
     "Sold one at a time. Unit left blank, which means Units."),
    ("Cement (loose)", "27", "22", "", "kg", "25", "30", "",
     "Weighed out of the sack. Unit is kg, so 12.5 kg can be sold."),
    ("Cement Bag 50 kg", "1350", "1180", "8964000333444", "", "", "", "50",
     "Sold as a whole bag: Unit blank (Units). The 50 goes in WEIGHT, which is "
     "for delivery only."),
    ("Floor Tile 12x12", "145", "112", "", "ft²", "135", "160", "",
     "Sold by area. Unit is ft2 and the customer buys 25.5 square feet."),
    ("GI Elbow 3/4 inch", "120", "78", "", "", "", "", "",
     "The simplest possible row: just a name and a price."),
]

SIMPLE_INTRO = (
    "Type one line per product on the Products sheet, then save the file and upload it "
    "with the Import button on Point of Sale > Products. Row 2 holds one example: type "
    "straight over it. More worked examples are further down this page.\n\n"
    "ONLY THE NAME AND THE SALES PRICE ARE NEEDED. Cost and Barcode are worth filling in "
    "if you have them to hand. The last column, External ID, fills itself as you type the "
    "name; never type in it.\n\n"
    "IF A CELL TURNS RED, something is wrong with it: the same name or the same barcode "
    "twice, a price with no name beside it, a cost higher than the sales price, or an "
    "empty External ID next to a filled-in name. Fix it before uploading.\n\n"
    "USING LIBREOFFICE OR WPS RATHER THAN EXCEL? Those programs do not recalculate a "
    "downloaded file unless you tell them to, so the External ID column stays empty and "
    "the whole last column turns red. Turn it on once: Tools > Options > Calc > Formula > "
    "Recalculation on File Load > Always recalculate, then close and reopen the file. "
    "Uploading with that column empty still works, but every re-upload then ADDS your "
    "products again instead of updating them.\n\n"
    "MADE A MISTAKE? Correct it in this same file and upload it again. Because of the "
    "External ID column, Odoo updates the products it already has instead of adding them "
    "a second time.\n\n"
    "AFTERWARDS, the products exist but are not on the till screen yet. Open "
    "Point of Sale > Products > Finish Product Setup, tick the rows you want, and set the "
    "category, unit and \"sell at the till\" for a whole group at once."
)

BLANK_LINE = NEWLINE + NEWLINE

ID_SOURCE_FIELDS = {
    "product": ("name",),
    "product_full": ("name",),
    "vendor": ("name",),
    "uom": ("name",),
    # A category name repeats under different parents ("Goods / Cleaning" and
    # "Tools / Cleaning" are both "Cleaning"), so the parent is part of the key.
    "product_category": ("name", "parent_id"),
    "pos_category": ("name",),
    # Every pack size of one product shares the product name; without the unit
    # the 5 kg bag and the 25 kg sack would be the same record.
    "product_package": ("product_id", "uom_id"),
}


def _id_source_columns(columns, key):
    """Column letters feeding the External ID formula for this template."""
    wanted = ID_SOURCE_FIELDS.get(key, ("name",))
    positions = {field: idx for idx, (_label, field, *_rest) in enumerate(columns)}
    letters = [xlsxwriter.utility.xl_col_to_name(positions[f])
               for f in wanted if f in positions]
    return letters or ["A"]


VENDOR_COLUMNS = [
    ("Name", "name", "What it is", True,
     "The supplier's name, as you would write it on a purchase order.",
     "The supplier's business name. This is the only column you must fill in.",
     "Karachi Pipe House", "", ""),
    ("Phone", "phone", "What it is", False,
     "Landline or mobile. Any format.",
     "A phone number for the supplier. Typed exactly as you enter it, so any "
     "local format is fine.",
     "021-32412345", "", ""),
    ("Mobile", "mobile", "What it is", False,
     "Mobile number, if different from the phone.",
     "A mobile number, if you keep one separately from the landline.",
     "0300-2345678", "", ""),
    ("Email", "email", "What it is", False,
     "Used when you email a purchase order or a payment note.",
     "The supplier's email address. Used when you send them a purchase order "
     "or a payment advice from Odoo. Leave blank if you only phone them.",
     "sales@karachipipe.example.pk", "", ""),
    ("City", "city", "How it is filed", False,
     "Town or city. Useful for sorting suppliers by area.",
     "The supplier's town or city, handy for grouping suppliers by area.",
     "Karachi", "", ""),
    ("Street", "street", "How it is filed", False,
     "Street address, for the purchase order and deliveries.",
     "Street address. Printed on purchase orders and used for deliveries.",
     "Shop 14, Timber Market", "", ""),
    _external_id_column("suppliers"),
]


VENDOR_INTRO = (
    "Type one line per supplier on the Products sheet, then save the file and upload it "
    "with the Import button on Customers & Vendors > Vendors. Row 2 holds one example: "
    "type straight over it." + BLANK_LINE +
    "ONLY THE NAME IS NEEDED. Everything else is worth filling in if you have it to hand, "
    "and can be added later on the supplier's own page." + BLANK_LINE +
    "IMPORT FROM THE VENDORS MENU, not from All Contacts. Uploading the same file under "
    "All Contacts creates ordinary contacts that will not appear when you raise a purchase "
    "order; the Vendors screen is what marks them as suppliers." + BLANK_LINE +
    "IF A CELL TURNS RED, the same supplier name appears twice, or the External ID next to "
    "a filled-in name is empty. Fix it before uploading." + BLANK_LINE +
    "MADE A MISTAKE? Correct it in this same file and upload it again: the External ID "
    "column means Odoo updates the suppliers it already has instead of adding them twice."
)

ESSENTIALS_NOTE = (
    "You do not have to fill all of this in. The columns are ordered so the nine that "
    "actually get a catalogue in come first; everything from 'Minimum Selling Price' "
    "rightwards is extra detail you can leave blank now and set later on the product form."
)

# key -> (columns, title, guide intro, filename served to the browser)
TEMPLATES = {
    "uom": (
        UOM_COLUMNS, "Unit of Measure Import  -  STEP 1",
        intro("unit", "Inventory > Configuration > Units of Measure",
              "Only needed for a size Odoo does not already have. Every unit that exists "
              "right now is listed on the Valid Values sheet and offered in the Reference "
              "Unit dropdown, so check there first. Never create a second unit with an "
              "existing name: two units called \"ft\" cannot convert to one another and "
              "stock silently goes wrong."),
        "unit_of_measure_import_template.xlsx",
    ),
    "product_category": (
        PRODUCT_CATEGORY_COLUMNS, "Product Category Import  -  STEP 2",
        intro("category", "Inventory > Configuration > Product Categories"),
        "product_category_import_template.xlsx",
    ),
    "pos_category": (
        POS_CATEGORY_COLUMNS, "Till Category Import  -  STEP 3",
        intro("category", "Point of Sale > Configuration > Categories"),
        "till_category_import_template.xlsx",
    ),
    "product": (
        PRODUCT_SIMPLE_COLUMNS, "Product List",
        SIMPLE_INTRO,
        "product_list.xlsx",
    ),
    # The full 23-column sheet is kept and still routable for anyone who wants
    # to set everything in one pass, but it is no longer what the Import screen
    # offers: it asks for five things the shopkeeper does not have to decide yet
    # and three that are cheaper to set in bulk afterwards.
    "product_full": (
        essentials_first(PRODUCT_COLUMNS), "Product Import (all fields)",
        intro("product", "Point of Sale > Products", ESSENTIALS_NOTE),
        "product_import_all_fields.xlsx",
    ),
    "vendor": (
        VENDOR_COLUMNS, "Supplier List",
        VENDOR_INTRO,
        "supplier_list.xlsx",
    ),
    "product_package": (
        POS_PACKAGE_COLUMNS, "Product Package Import  -  STEP 5",
        intro("pack size", "Point of Sale > Products > Product Packages",
              "Use this only when you sell the SAME product in more than one size, e.g. "
              "sugar loose by the kilo and also as a 5 kg bag. Each pack gets its own "
              "barcode and price, while stock stays counted in the product's own unit, so "
              "selling one 5 kg bag takes 5 kg off the shelf. If a product is only ever "
              "sold one way, set its Unit on the product itself and ignore this file."),
        "product_package_import_template.xlsx",
    ),
}


def filename_for(key):
    return TEMPLATES[key][3]


def build_workbook(env, key):
    """Return the .xlsx for one template as bytes, built against `env`.

    Generated per download rather than shipped as a static file: that is the
    only way the dropdowns can hold the categories, units, brands and vendors
    that exist in THIS database at THIS moment.
    """
    columns, title, guide_intro, _filename = TEMPLATES[key]

    # Resolve the pick-lists once. A column whose source yields nothing (no
    # brands defined yet, say) simply gets no dropdown rather than an empty one.
    lists = {}
    for _label, field, *_rest in columns:
        source = live_values.source_for(field, key)
        if not source:
            continue
        try:
            values = source(env)
        except Exception:          # noqa: BLE001 - a missing optional model must
            continue               # not take the whole download down
        if values:
            lists[field] = values

    output = io.BytesIO()
    book = xlsxwriter.Workbook(output, {"in_memory": True})
    _write_sheets(book, columns, title, guide_intro, lists, key)
    book.close()
    return output.getvalue()


# Which columns make a row unique, per template. Getting this wrong is not
# cosmetic: too few and two different rows share an id, so the second silently
# overwrites the first on import.
def _all_known_columns():
    """Every column tuple defined in this module, for label lookups."""
    for table in (PRODUCT_COLUMNS, PRODUCT_SIMPLE_COLUMNS, PRODUCT_CATEGORY_COLUMNS,
                  POS_CATEGORY_COLUMNS, POS_PACKAGE_COLUMNS, UOM_COLUMNS):
        for column in table:
            yield column


def _values_sheet(book, lists):
    """Write every pick-list to a visible sheet and return per-field ranges.

    Visible, not hidden: the dropdown is an Excel feature and renders
    inconsistently in LibreOffice and Google Sheets, so the same information has
    to be readable as plain cells. It also gives the user somewhere to copy a
    name from when a column allows several values separated by commas.
    """
    if not lists:
        return {}
    sheet = book.add_worksheet(VALUES_SHEET)
    head = book.add_format({"bold": True, "bg_color": "#333333", "font_color": "white",
                            "border": 1, "text_wrap": True, "valign": "vcenter"})
    cell = book.add_format({"border": 1})
    note = book.add_format({"italic": True, "font_color": "#666666", "text_wrap": True})

    sheet.merge_range(0, 0, 0, max(len(lists) - 1, 1),
                      "These are the values that exist in your database right now. "
                      "The matching columns on the Products sheet offer them as dropdowns; "
                      "you can also copy from here. Anything not on this list has to be "
                      "created before the import, or created by it.", note)
    ranges = {}
    # Head the columns with the LABEL the shopkeeper sees on the Products sheet,
    # not the technical field name. This sheet exists to be read and copied from;
    # heading it "categ_id" and "seller_ids/partner_id" defeated the entire point.
    labels = {field: label for label, field, *_rest in _all_known_columns()}
    for col, (field, values) in enumerate(sorted(lists.items())):
        sheet.write(1, col, labels.get(field, field), head)
        for row, value in enumerate(values, start=2):
            sheet.write(row, col, value, cell)
        sheet.set_column(col, col, 30)
        letter = xlsxwriter.utility.xl_col_to_name(col)
        ranges[field] = "='%s'!$%s$3:$%s$%d" % (VALUES_SHEET, letter, letter, len(values) + 2)
    sheet.freeze_panes(2, 0)
    return ranges


def _write_sheets(book, columns, title, guide_intro, lists, key):
    def header_format(group, required):
        fmt = {"bold": True, "bg_color": GROUPS[group], "font_color": "white",
               "border": 1, "text_wrap": True, "valign": "vcenter", "align": "center"}
        if required:
            fmt.update({"border": 5, "border_color": "#C00000"})
        return book.add_format(fmt)

    cell = book.add_format({"border": 1, "valign": "top"})
    money = book.add_format({"border": 1, "num_format": "#,##0.00"})
    formula_cell = book.add_format({"border": 1, "bg_color": "#F2F2F2",
                                    "font_color": "#999999", "italic": True})

    sheet = book.add_worksheet("Products")   # must stay first: the importer reads sheet 1
    sheet.freeze_panes(1, 1)
    sheet.set_row(0, 34)

    ranges = _values_sheet(book, lists)

    for idx, (label, field, group, required, brief, helptext, *examples) in enumerate(columns):
        sheet.write(0, idx, label, header_format(group, required))
        has_list = field in ranges
        comment_lines = [
            group.upper(),
            "REQUIRED - cannot be blank" if required else "Optional - may be left blank",
            "",
            helptext,
            "",
        ]
        if has_list:
            comment_lines += [
                "Pick from the dropdown in any cell below, or copy from the "
                "'%s' sheet." % VALUES_SHEET,
                "",
            ]
        comment_lines.append("(Odoo field: %s)" % field)
        sheet.write_comment(0, idx, NEWLINE.join(comment_lines),
                            {"width": 300, "height": 210})
        sheet.set_column(idx, idx, max(18, min(len(label) + 4, 32)))

        rule = {"validate": "any"}
        if has_list:
            rule = {
                "validate": "list",
                "source": ranges[field],
                # NOT a cage. A user importing brand-new categories in the same
                # file must still be able to type a name that does not exist
                # yet, and columns taking several comma-separated values could
                # never satisfy a strict list.
                "show_error": False,
            }
        rule.update({
            "input_title": ("* " + label if required else label)[:TITLE_MAX],
            "input_message": (brief + ("  (pick from the list)" if has_list else ""))[:MSG_MAX],
        })
        sheet.data_validation(1, idx, MAX_ROW, idx, rule)

        if field == "id":
            # Self-filling and visibly not-for-typing. Written for every usable
            # row up front, because a formula the user has to drag down is a
            # formula that will not be dragged down.
            id_cols = _id_source_columns(columns, key)
            for row in range(1, MAX_ROW + 1):
                sheet.write_formula(row, idx,
                                    external_id_formula(row + 1, id_cols),
                                    formula_cell, "")
            continue

        for row, value in enumerate(examples, start=1):
            if value != "":
                sheet.write(row, idx, value, money if label in MONEY_HEADERS else cell)

    _red_flags(book, sheet, columns)
    _write_guide(book, columns, title, guide_intro, lists)


def _red_flags(book, sheet, columns):
    """Colour a cell as it is typed when it is going to fail the import.

    Conditional formatting rather than data validation on purpose: validation
    dropdowns and error popups are an Excel feature that render inconsistently
    in LibreOffice and WPS, which is what a Pakistani shop is likely to have,
    whereas formula-based conditional formatting is portable. This is the first
    feedback the shopkeeper gets before uploading rather than after.
    """
    headers = {label: idx for idx, (label, *_rest) in enumerate(columns)}
    bad = book.add_format({"bg_color": "#FFC7CE", "font_color": "#9C0006"})
    last = MAX_ROW + 1

    def col_of(label):
        idx = headers.get(label)
        return xlsxwriter.utility.xl_col_to_name(idx) if idx is not None else None

    name, price, cost, barcode = (col_of(x) for x in
                                  ("Name", "Sales Price", "Cost", "Barcode"))

    if name:
        rng = "%s2:%s%d" % (name, name, last)
        sheet.conditional_format(rng, {
            "type": "formula", "format": bad,
            "criteria": '=AND($%s2<>"",COUNTIF($%s$2:$%s$%d,$%s2)>1)'
                        % (name, name, name, last, name),
        })
    if barcode:
        rng = "%s2:%s%d" % (barcode, barcode, last)
        sheet.conditional_format(rng, {
            "type": "formula", "format": bad,
            "criteria": '=AND($%s2<>"",COUNTIF($%s$2:$%s$%d,$%s2)>1)'
                        % (barcode, barcode, barcode, last, barcode),
        })
    if name and price:
        # A row with a price but no name is the commonest slip: a line typed
        # one row below where the eye thinks it is.
        sheet.conditional_format("%s2:%s%d" % (name, name, last), {
            "type": "formula", "format": bad,
            "criteria": '=AND($%s2="",$%s2<>"")' % (name, price),
        })
    if price and cost:
        sheet.conditional_format("%s2:%s%d" % (cost, cost, last), {
            "type": "formula", "format": bad,
            "criteria": '=AND($%s2<>"",$%s2<>"",$%s2>$%s2)' % (cost, price, cost, price),
        })

    # A named row whose External ID never filled in. That means the spreadsheet
    # did not run the formula -- LibreOffice and WPS ship with "Recalculation on
    # File Load" set to Never for foreign files, so the column silently stays
    # empty. The row still imports, which is the danger: it imports as a NEW
    # product every time, so correcting a price and re-sending the file
    # duplicates the whole catalogue instead of updating it. That failure is
    # invisible until the product list has doubled, so it gets a red cell like
    # any other mistake.
    external = col_of("External ID")
    if name and external:
        sheet.conditional_format("%s2:%s%d" % (external, external, last), {
            "type": "formula", "format": bad,
            "criteria": '=AND($%s2<>"",$%s2="")' % (name, external),
        })


def _write_guide(book, columns, title, guide_intro, lists):
    guide = book.add_worksheet("READ ME FIRST")
    for col, width in enumerate((30, 20, 12, 88)):
        guide.set_column(col, col, width)

    h1 = book.add_format({"bold": True, "font_size": 15})
    h2 = book.add_format({"bold": True, "font_size": 11, "bg_color": "#EEEEEE", "border": 1})
    wrap = book.add_format({"text_wrap": True, "valign": "top", "border": 1})
    plain = book.add_format({"valign": "top", "border": 1})
    bold_cell = book.add_format({"valign": "top", "border": 1, "bold": True})
    note = book.add_format({"text_wrap": True, "valign": "top"})
    steps_fmt = book.add_format({"text_wrap": True, "valign": "top", "bg_color": "#FFF4CE",
                                 "border": 1, "font_name": "Consolas", "font_size": 10})

    guide.write(0, 0, title, h1)
    guide.merge_range(1, 0, 9, 3, guide_intro, note)
    row = 11

    is_simple = any(field == "id" for _l, field, *_r in columns)
    if is_simple:
        # A picture of filled rows, not rows in the sheet. Example rows have to
        # be deleted, and the ones that are not deleted become junk products;
        # this cannot be imported by accident.
        guide.write(row, 0, "What a filled sheet looks like", h2)
        for col in (1, 2, 3):
            guide.write(row, col, "", h2)
        row += 1
        example_head = book.add_format({"bold": True, "bg_color": "#DDDDDD", "border": 1,
                                        "text_wrap": True, "align": "center"})
        example_cell = book.add_format({"border": 1, "align": "center"})
        name_cell = book.add_format({"border": 1})
        why_cell = book.add_format({"border": 1, "text_wrap": True, "valign": "top",
                                    "italic": True, "font_color": "#555555"})
        grey = book.add_format({"font_color": "#999999", "italic": True})
        # Widen for the worked table, then the notes column carries the reason.
        for col, width in enumerate((26, 11, 9, 16, 8, 7, 7, 8, 52)):
            guide.set_column(col, col, width)
        headings = ("Name", "Sales Price", "Cost", "Barcode", "Unit",
                    "Min", "MRP", "Weight", "Why it is filled in this way")
        for col, label in enumerate(headings):
            guide.write(row, col, label, example_head)
        row += 1
        for name, price, cost, barcode, uom, mn, mx, weight, why in SIMPLE_WORKED_EXAMPLE:
            guide.write(row, 0, name, name_cell)
            for col, value in enumerate((price, cost, barcode, uom, mn, mx, weight), start=1):
                guide.write(row, col, value, example_cell)
            guide.write(row, 8, why, why_cell)
            row += 1
        guide.write(row, 0,
                    "Blank is fine everywhere except Name and Sales Price. "
                    "Blank Unit means Units; blank Min/MRP means no price limit. "
                    "The External ID column is not shown here because it fills itself.",
                    grey)
        row += 3
    else:
        guide.merge_range(row, 0, row + 5, 3, STEPS, steps_fmt)
        row += 7
    for col, label in enumerate(("Colour key", "", "", "What those columns are about")):
        guide.write(row, col, label, h2)
    row += 1
    for group in [g for g in GROUPS if any(c[2] == g for c in columns)]:
        guide.write(row, 0, group, book.add_format(
            {"bg_color": GROUPS[group], "font_color": "white", "bold": True,
             "border": 1, "align": "center"}))
        for c in (1, 2):
            guide.write(row, c, "", plain)
        guide.write(row, 3, GROUP_BLURB[group], wrap)
        row += 1
    guide.write(row, 0, "Red outline", book.add_format(
        {"border": 5, "border_color": "#C00000", "bold": True, "align": "center"}))
    for c in (1, 2):
        guide.write(row, c, "", plain)
    guide.write(row, 3, "This column is required. Every other column may be left blank.", wrap)
    row += 3

    for col, label in enumerate(("Column heading", "Group", "Required?", "What to put in it")):
        guide.write(row, col, label, h2)
    row += 1
    for label, field, group, required, brief, helptext, *_ in columns:
        guide.write(row, 0, label, bold_cell if required else plain)
        guide.write(row, 1, group, plain)
        guide.write(row, 2, "Required" if required else "Optional", plain)
        suffix = ""
        if field in lists:
            suffix = ("  [%d existing value(s) offered as a dropdown; see the '%s' sheet]"
                      % (len(lists[field]), VALUES_SHEET))
        guide.write(row, 3, helptext + suffix, wrap)
        row += 1
