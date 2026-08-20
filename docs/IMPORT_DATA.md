# Setting up a hardware & sanitary shop from zero

> The spreadsheets this describes live in `import-data/` at the project root.
> This file was moved here on 19 August 2026 so all documentation sits in one folder.

Seven sheets, uploaded in order. Every one has been imported for real against a
live Odoo and rolled back, so the headers are known to map and the values are
known to land — not just to look right in Excel.

**Upload each sheet, check the result, then move to the next.** The order is not
a preference: each sheet refers to records the earlier ones create. Skip ahead
and the import fails with *"No matching records found"*.

## Where each list lives

Odoo buries these two and three levels deep. Rather than hunting, type the name
into the **sidebar search box** under the OStore logo, or press `Ctrl+K` then
`/`. Both search every menu in every app.

| Sheet | Menu path |
|---|---|
| 1 categories | Inventory → Configuration → **Products** → Categories |
| 2 till sections | Point of Sale → Configuration → **Products** → PoS Product Categories |
| 3 vendors | Contacts → Vendors |
| 4 units | Inventory → Configuration → Units & Packagings |
| 5 products | Inventory → Products → Products |
| 6 packages | Point of Sale → Products → Product Packages |
| 7 opening stock | Inventory → Operations → **Adjustments** → Physical Inventory |

The **Products** step in paths 1 and 2 is a grouping level that is easy to walk
past — and note there are two different lists called *Categories*, one in each
of those rows. The first is your filing tree; the second is the till buttons.

---

## Before anything: two settings

### Turn variants off

**Inventory → Configuration → Settings → Products → untick "Variants" → Save**

**Why.** Variants are one product in several versions — one *Elbow* in 1/2", 3/4"
and 1". It sounds like what a hardware shop wants, and it isn't, for one
concrete reason: **Minimum Selling Price and MRP live on the product, not on the
variant.** All sizes would share one price floor. Set it to protect the 1" and
you cannot sell the 1/2" at all; set it for the 1/2" and the 1" can be sold at a
loss. Different sizes are different products.

Turning it off also removes the *Product Variants* and *Attributes* menus, which
are two doors you never want to walk through by accident.

### Leave the warehouse alone

**Nothing to do.** Odoo creates one warehouse with one stock location, and that
is correct for a single shop.

*Warehouses, Locations, Operations Types, Storage Categories, Putaway Rules* are
for companies with several buildings and racking rules about which shelf holds
what. Configuring them for one shop adds steps to every sale and gains nothing.

---

## 1. `1_categories.xlsx` → 19 categories

**Inventory → Configuration → Products → Categories → Import**

**What this is.** Your filing tree, used for reports, stock valuation and
accounting. Nested:

```
Plumbing
├── Pipes
├── Pipe Fittings
│   ├── Elbow
│   ├── Tee
│   └── Coupling
└── Valves & Taps
Sanitary · Electrical · Paint & Chemicals · Cement & Building
Tiles & Flooring · Hardware & Tools
```

**Why first.** The product sheet names its category as text. If the category
does not exist yet, that row fails.

**Why it is a tree.** Ask for a report on *Pipe Fittings* and elbows, tees and
couplings roll up together without listing them. That only works if the parent
exists as a real record.

**The two rules in the file:** the *Name* column is the bare name (`Elbow`), the
*Parent Category* column is the full path (`Plumbing / Pipe Fittings`), and
parents are listed **above** their children — Odoo reads the file top to bottom.

---

## 2. `2_till_sections.xlsx` → 6 sections

**Point of Sale → Configuration → Products → PoS Product Categories → Import**

There is a *Products* grouping between *Configuration* and this list — easy to
miss. Quicker: type `PoS Product` into the sidebar search box, or press
`Ctrl+K` then `/`.

**What this is.** The buttons a cashier taps to filter the product grid.
Completely separate from step 1.

**Why flat and only six.** These match your aisles, not your filing tree. If
every sub-category were a button the cashier would face forty of them and have
to scroll — slower than typing `elbow` in the search box.

**This step is optional.** If your staff scan barcodes and use search, they will
never touch these. The till works with zero sections.

---

## 3. `3_vendors.xlsx` → 8 suppliers

**Contacts → Vendors → Import**

**What this is.** Who you buy from.

**Why before products.** The product sheet has a *Vendors / Vendor* column. That
is what later drives purchase orders, the "Products with No Assigned Vendor"
report, and knowing who to reorder from when something runs out.

---

## 4. `4_units_optional.xlsx` → 3 units — **skip unless you need them**

**Inventory → Configuration → Units & Packagings → Import**

**Look before you import.** Odoo plus your module already ship almost everything
a Pakistani hardware shop uses:

```
kg · g · Ton · L · ml · m · cm · mm · ft · in · m² · ft²
40 kg Bag · 50 kg Sack · 25 kg Sack · Tin of 4 L · Drum of 20 L
Roll of 100 m · Roll of 90 m · Bundle of 20 m · Length of 20 ft
Box of 10 · Box of 20 · Carton of 24 · Tile Box (20 sq ft) · Set · Pair
```

This sheet adds only three the paint and steel trade uses that Odoo does not
have: **Quarter (0.9 L)**, **Gallon (3.64 L)**, **Bundle of 10**.

**What a unit actually decides.** Whether the till accepts a fraction. A product
sold in `ft` lets the cashier key `2.75`. A product in `Units` does not — half a
tap is not a thing. Get this right and the till stops a whole class of mistake
on its own.

---

## 5. `5_products.xlsx` → 22 products

**Inventory → Products → Products → Import**

**Import 3 rows first.** Delete the rest, upload, look at the result, then come
back and do all 22. Every mistake you would make across 22 rows shows up in the
first 3, and fixing 3 takes a minute.

The set deliberately covers every way a hardware shop sells:

| Sold by | Unit | Example |
|---|---|---|
| the piece | `Units` | Elbow, tap, switch, hammer |
| length | `ft`, `m` | PVC pipe, electric wire |
| weight | `kg` | Cement |
| volume | `L` | Emulsion and enamel paint |
| area | `ft²` | Floor tiles |

It also includes **PVC Pipe 1 inch — Heavy** and **— Standard** as two separate
products at 300 and 150, with their own price floors of 280 and 140. That is the
pattern for quality grades, and the reason variants are switched off.

**Columns worth understanding:**

- **Minimum Selling Price** — the floor. A cashier cannot go below it without a
  manager. This is the column that protects your margin, and it is per product.
- **Maximum Retail Price (MRP)** — the ceiling, so nobody overcharges a customer.
- **Track Inventory = TRUE** — required, or the product holds no stock and
  step 7 has nothing to count.
- **Available in POS = TRUE** — what actually puts it on the till.
- **Barcode is blank on purpose.** Odoo generates a valid one on import. Where a
  product has a real printed barcode, scan it into the product form afterwards —
  a scanned code is never overwritten.

---

## 6. `6_packages.xlsx` → 9 pack sizes

**Point of Sale → Products → Product Packages → Import**

**What a package is.** The *same* product in a bigger container, with its own
barcode and its own price.

**The problem it solves.** Paint is 450/litre. A 4 L tin sells for 1700, not
1800. Without a package the cashier types `4`, the till charges 1800, and
someone has to remember to discount it every single time. With a package they
scan the tin: 4 litres added, 1700 charged, nothing to remember.

**Stock stays in one pool.** Sell a tin and your paint drops by 4 litres. Sell 2
loose litres and it drops by 2. You never count "tins" separately.

**No quantity column** — Odoo works it out from the unit. `Tin of 4 L` is 4
litres.

**Requires step 5** — a package points at a product that must already exist.

---

## 7. `7_opening_stock.xlsx` → 22 lines

**Inventory → Operations → Adjustments → Physical Inventory → Import**

**What this is.** How much you have on the shelf right now.

**Two steps, on purpose.** The import fills the *Counted* column; it does **not**
change your stock. Review the list, then press **Apply**. A slipped decimal —
20000 kg of cement instead of 2000 — is caught while it is still just a number
in a column, rather than after it has become a stock move and a valuation entry.

**Quantities are in the product's own unit.** 2000 kg of cement, not 40 bags.
Odoo knows a 50 kg sack is 50 kg.

---

## Then check it works

**Point of Sale → Dashboard → New Session**

| # | Do | Expect |
|---|---|---|
| 1 | Tap **Pipes & Fittings** | Only pipes and fittings show |
| 2 | Add `Elbow 1/2 inch PVC` | 45 |
| 3 | Add `Cement OPC`, quantity 50 | 1400 — the loose kg rate |
| 4 | Scan the **50 kg Sack** barcode | 50 kg added, charged **1350** |
| 5 | Add `PVC Pipe Heavy`, type **2.5** | Accepted — sold by the foot |
| 6 | Add `Elbow 1/2 inch`, type **2.5** | **Refused** — pieces are whole |
| 7 | Price the elbow at **30** | **Blocked** — below the 40 floor |
| 8 | Price it at **50** | Allowed — inside 40–55 |
| 9 | Pay and print | Receipt names the pack size |
| 10 | Close the session | Journal entry posts |
| 11 | Check stock | Cement down 50 kg |

Steps 4, 6 and 7 are the ones worth caring about — they are the packaging,
measurement and price-floor systems proving they actually work at the counter.

---

## If an import goes wrong

Every sheet has an **External ID** column that fills itself. Fix the mistake in
the same file and upload it again — rows Odoo has already seen are **updated**,
not added a second time. That is your undo, and it is why the column is there.

If you open these in **LibreOffice or WPS**, check the External ID column has
values before uploading. Those apps do not always recalculate on open, and a
blank External ID is the one failure that duplicates a whole catalogue on the
second upload. These files ship with the values written out, so this only bites
if you add rows of your own.

Take a backup before the big one:

```bash
pg_dump -h 127.0.0.1 -U postgres -Fc -d ostore_live \
        -f /var/backups/odoo/before_import.dump
```
