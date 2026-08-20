# Murshid Store — import sheets

> The spreadsheets this describes live in `import-data/murshid-store/` at the
> project root. This file was moved here on 19 August 2026 so all documentation
> sits in one folder.

Built from **both** of your stock lists: `Murshid Store.xlsx` and
`PDF ITEM S.pdf`. **446 products** across sanitary, plumbing, electrical,
hardware and gas, plus the categories, till sections, brands and quality tags
they depend on.

Every sheet has been imported for real into a live Odoo, in this order, and
then rolled back — so the headers are known to map and the values are known to
land.

> Two files were open in Excel when this was generated, so the new versions sit
> beside them as `2_till_sections.UPDATED.xlsx` and `4_products.UPDATED-Roman-name-fix.xlsx`.
> Close Excel, delete the originals, drop the `.UPDATED` — or just import those.

## Upload in this order

| # | File | Where | Rows |
|---|---|---|---|
| 1 | `1_categories.xlsx` | Inventory → Configuration → Products → **Categories** | 31 |
| 2 | `2_till_sections.xlsx` | Point of Sale → Configuration → Products → **PoS Product Categories** | 5 |
| 3 | `3b_brands.xlsx` | Point of Sale → Products → **Product Brands** | 69 |
| 4 | `3c_quality_tags.xlsx` | Inventory → Configuration → Products → **Product Tags** | 5 |
| 5 | `4_products.UPDATED-Roman-name-fix.xlsx` | Inventory → Products → **Products** | 446 |
| — | `3_vendors.xlsx` | Contacts → **Vendors** | empty, see below |

The order is not a preference. Products name their category, till section,
brand and tag as text, so all four must exist first. Skip ahead and you get
*"No matching records found"*.

## Before you upload: fill in Sales Price

**`4_products.UPDATED-Roman-name-fix.xlsx`, the amber column.** Neither source list has prices, so
this is the one thing only you can supply.

- **Sales Price** — required. Per unit shown in the Unit column: **per foot**
  for pipe and wire, per piece for everything else.
- **Cost** — optional but worth it; it drives profit reporting.
- **Minimum Selling Price** / **MRP** — optional, per product. The floor and
  ceiling a cashier may sell between.

Do **3 rows first**, import, look at the result, then delete those and do all
446.

## Units

| Unit | Count | Meaning |
|---|---|---|
| `Units` | 402 | Sold by the piece |
| `m` | 21 | By the metre — wire from the first list |
| `ft` | 18 | **By the foot, cut to length** — Section Pipe, Garden Pipe, Electric Utility Pipe, Casin Pipe, submersible wire. The till accepts `7.5`. |
| `Set` | 5 | Bathroom sets, sold complete |

Your PDF's `RFT` (running feet) became `ft`, `PCS` and `NOS` became `Units`,
`SET` became `Set`. `BDL` (bundle, on Rassi) became `Units` — Odoo has no
bundle unit, so one unit means one bundle. Price it accordingly.

## Quality grade

Your 1–4 grade is a **product tag**, not part of the name.

The first attempt put it in Internal Reference and Odoo **rejected the whole
import**: SKUs must be unique, so a hundred products cannot share `Q1`. Tags
have no such rule, and they give you a one-click filter in the product list —
which is what a grade is for.

It stays out of the name deliberately. Every row carries exactly one grade, so
446 names ending `Q3` would be noise your cashier cannot act on. The two rows
that genuinely differ by grade alone already carry it: *Complete Hand Shower
Quality 3* and *Quality 4*, and the two *Bathroom Set Lever* rows.

**140 products carry a grade** — the ones from the PDF list. The Excel list
recorded none.

## Where the two lists overlapped

Only **18 names** appeared in both, all GI fittings:

```
GI Elbow     1/2, 3/4, 1, 1-1/4, 1-1/2 inch
GI Tee       1/2, 3/4, 1, 1-1/4, 1-1/2 inch
GI Socket    1/2, 3/4, 1, 1-1/4, 1-1/2 inch
GI MF Elbow  1/2, 3/4, 1 inch
```

**The PDF version was kept.** Your Excel row was `GI Elbows | 1/2", 3/4", 1",
1 1/4", 1 1/2"` — no brand, no grade. The PDF gives the identical five sizes
*with grade 3*, so the Excel copy carried strictly less information and there
was nothing to tell the two apart. Keeping both would have put two
identical-looking products in front of the cashier and split each item's stock
between them.

**If those really are two different lines you stock separately** — say a
cheaper GI elbow alongside the grade-3 one — tell me what distinguishes them
and I will split them back out in one step.

Everything else from both lists is kept. **120 of the PDF's 140 products were
new**, including the whole brass tap range, PVC Solution in five sizes,
Solution E2, Solution Steeled, Section Pipe, Connection Pipe, Basin/West Pipe,
bathroom sets, Latta, Garden Pipe, Electric Utility Pipe, W.C.s, Wash Basin,
P-Traps and Rassi.

## What was done to your data

**Sizes became separate products.** `GI Elbows | 1/2", 3/4", 1", 1 1/4", 1 1/2"`
became five products. Each size has its own price, stock and price floor.
Delete any size you do not stock.

**Product names keep the counter's Roman Urdu wording** (2026-08-19: Garam Ka Wall, Cooler Tooti, Gool Brush, Fix Paana, Nalt Bolt, Flynger, Kict, Steill … restored as written; only sizes are numeric).

**Urdu and Punjabi sizes were translated** — adha 1/2, pona 3/4, ik 1, sewa
1-1/4, der 1-1/2, dhai 2-1/2, quater 1/4, "pona by der" a 3/4 x 1-1/2 reducer.

**Excel had eaten your fractions.** Sizes stored as `2026-01-02` were **1/2**
typed into a date cell. All reversed. Format that column as **Text** next time.

**Colour counts were NOT expanded.** `PVC, 12 colors` is one product with a
colour choice, not twelve products.

**Names were made unique.** Where two makers supply the same item — `Gas wall`
from Ifan and from Double Line MS 58, both 1/2 inch — the brand joins the name.
This matters: the External ID comes from the name, so two products sharing a
name share one ID and **the second silently overwrites the first**.

**Your five answers of 2026-08-14 are applied**: Handle Valve `1/5` corrected
to `1/2` and merged with its duplicate row; L Key limited to 4, 5, 6, 7, 12 mm;
Cutting Disc 14 inch under Gold Elephant; Glass Raak Maal kept as one product;
Paani Ki Ghoti moved to Hand Tools.

## Names kept as you wrote them

Suspected typos were **not** silently corrected — they are your counter's
words, and guessing would be worse than leaving them:

`Section Pipe` (likely Suction) · `Wash Besan` (Basin) · `Casin Pipe` (Casing) ·
`Summer Sibble Pump` (Submersible) · `Side Piller Cock` (Pillar) · `Bip Cock`
(Bib) · `Camot` (likely Commode) · `Basin/West Pipe` (likely Waste)

Rename any of them in Odoo after import, or tell me and I will fix the sheet.

## Three rows that still need you

- **Summer Sibble Pump** — no size or horsepower anywhere in the source. It
  cannot be priced sensibly until you add one.
- **Casin Pipe / Filter Pipe** — no diameter given.
- **Baby P-Trap 2 inch** — quality reads `8`, outside your 1–4 scale. Kept
  verbatim rather than guessed.

## `3_vendors.xlsx` is empty on purpose

Both lists recorded **brands** — Steelex, Toshiba, RBS, China — which is who
*made* it, not who you *buy from*. Those went into `3b_brands.xlsx`. Type your
real suppliers into the vendors sheet whenever you like; nothing depends on it.

## The External ID column

Ignore it. It fills itself, including on rows you add — 200 spare rows below
the data already carry the formula.

Its job: if you get a price wrong, fix it in the same file and upload again.
Odoo recognises those rows and **updates** them instead of adding your
catalogue a second time. If a cell there ever shows **red**, that row has a
name but no ID — retype the name and it fills.

## After importing

Opening stock: **Inventory → Operations → Adjustments → Physical Inventory**.
Enter your counts, then press **Apply**. Neither source list has quantities, so
there is no sheet for it.
