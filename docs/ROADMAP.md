# POS Retail — Plan & Findings

**As of 20 August 2026.** Module version `19.0.3.6.1`, branch
`feature/receipts-permissions-ledger`.

What this file is: the work still owed against the customer/vendor requirements
document, plus the problems found in the existing build while reading the code
to plan that work. Everything below was checked against source, not recalled —
file and line references are given so each claim can be re-checked.

Legend: ✅ done · ▶ planned · ⚠️ finding, needs a decision · ❓ open question

---

## 1. Done since the last release

### ✅ Product import sheet — Roman Urdu names restored
`import-data/murshid-store/4_products.UPDATED-Roman-name-fix.xlsx`

The sheet had been built with English product names translated from the
counter's own Roman Urdu wording. 110 rows were restored to the wording the shop
actually uses: `Garam Ka Wall CPVC`, `Thande Ka Wall PVC`, `Cooler Tooti`,
`Gool Brush`, `Fix Paana`, `Ring Fix`, `Nalt Bolt`, `Flynger`, `Basin Kict`,
`Combalt Kict`, `Steill Round Vest Jali`, `Bip Tank Cap PVC Main Hole`,
`Gas Chabi Key Bhari Or Halki Wali`, `Rakmall Sheesy Wala`, and the rest.

- Sizes were **left numeric** (`1/2`, `3/4`, `1-1/4 inch`) rather than
  adha / pona / sewa — 446 rows already use that format and it compares faster
  at a glance. Reversible if the shop prefers otherwise.
- External IDs regenerated for all 110 renamed rows. No duplicate names, no
  duplicate IDs, 446 products intact.
- The English-name version is kept as
  `4_products.UPDATED.backup-english-names.xlsx`.

⚠️ **If those products were already imported under the English names**, re-uploading
this sheet creates them a second time rather than renaming them. A rename-only
sheet keyed on the old External IDs would be needed instead. Not yet confirmed
either way.

❓ `Keelein` (nails) appears in the Hardware source list but is missing from the
products sheet. Add it?

### ✅ Receipt screen went blank on validate — fixed
`static/src/receipt/receipt.xml` · `static/src/overrides/receipt_screen_guard.js`
Module `19.0.3.6.1`.

Reported from the live server: validating a sale showed a blank screen instead of
the receipt, and refreshing the receipt URL threw an Owl error. Two separate
faults, both now fixed.

**1. Our bug — the SKU line.** The receipt read
`line.pos_retail_package_id.sku` guarded only by the *Show SKU* setting, not by
the package existing. Any line sold **without** a package — nearly every line —
threw `Cannot read properties of undefined (reading 'sku')` and took the whole
receipt down. It stayed hidden because it only fires once *Show SKU* is switched
on, which the new server had and the old one did not.

Fixed with optional chaining, and every other chain in both receipt templates was
audited: the ones whose middle link is not proven by its own `t-if`
(`uom_id.name`, `payment_method_id.name`, `pos_retail_price_manager_id.name`,
`order.company.name`) were hardened too. A receipt that fails to render loses the
sale's paperwork, so none of them is worth a hard crash.

**2. Core shortcoming — reloading a receipt URL.** The POS loads only *draft*
orders at start-up (`pos_order.py._load_pos_data_domain`), so a finalised sale is
never in memory after a refresh. Core spots the miss and calls `navigate()`, but
that does not abort the setup already running, and the next line reads
`this.currentOrder.getPartner()` off `undefined` — blank page, no way back.
`receipt_screen_guard.js` falls back to the open order so setup survives the one
frame before core's redirect lands, and the user ends on the product screen.

⚠️ To reprint an old receipt the supported path is **Orders → select → Print
Receipt**. A receipt URL is a live in-app route, not a shareable link.

### ✅ Colour palette extended from 12 to 20
`static/src/backend/color_list.js` · `color_list.scss` ·
`static/src/overrides/color_list_pos.scss`

Odoo's product-colour picker is a hard-coded list of twelve mid-tone pastels
(`web/static/src/core/colorlist/colorlist.js`). Twelve soft tints is not enough
separation for a counter that stocks five sizes of the same elbow, and there was
no black at all. Eight darker, saturated colours were appended at indices 12–19:
Black, Grey, Brown, Maroon, Navy, Forest, Brass, Slate.

Two implementation notes for whoever touches this next:

- **The stored value is a plain integer index.** Appending is safe; inserting or
  reordering silently repaints every product already coloured.
- At the till Odoo never paints the raw colour — it lightens each one so the
  product name stays readable, which turns black into an unreadable mid-grey.
  The new set therefore uses a pale background with the colour at full strength
  on the card's 6px bottom stripe. Contrast was checked: all eight pass WCAG AA
  for both the picker tick and the product name.

---

## 2. Findings — existing behaviour worth deciding about

### ⚠️ 2.1 A pricelist can sell below the Minimum Selling Price
`static/src/overrides/price_override.js`

Minimum Selling Price and MRP are enforced on the two **manual** paths only:
adding a product (`addLineToCurrentOrder`, the price popup) and retyping a
price on a cart line (`OrderSummary.setLinePrice`). Both demand a manager PIN
and a reason outside the range.

A **pricelist rule** that computes a price below the minimum is applied by core
with no warning, no PIN and no audit entry. So the minimum is a guard against
cashiers, not a floor on the product.

Decide: is the minimum meant to be a hard floor? If yes, the pricelist-computed
price needs the same check. If no, it should be renamed so it stops reading like
one.

### ⚠️ 2.2 `wholesale_price` is an orphan field
`models/product_template.py:23`

The field is defined and stored, sits on the General Information tab under
Selling Price Range, and **nothing reads it**. It does not feed the seeded
`Wholesale` pricelist despite the name. Meanwhile the Prices tab is the real
place to set a wholesale price.

Two things called "wholesale" on one form, one of which does nothing, is a trap
for whoever sets up products. Either wire it to the Wholesale pricelist or
remove it.

### ⚠️ 2.3 The pricelist rule dialog defaults to the everyone-list
The **Create Pricelist Rules** dialog opens with Pricelist = `Default (PKR)` —
the list every ordinary walk-in customer is on. Saving without changing it
re-prices the product for **everybody**, which is almost never what someone
adding a "wholesale price" intends.

Cheap fix worth considering: default that field to blank and make it required,
so the choice has to be made consciously.

### ⚠️ 2.4 "Category" means two different things on one form
General Information → **Category** is the accounting and reporting group.
Point of Sale tab → **Category** is the till button group. Both are required for
a product to work properly and they are not interchangeable. This is core Odoo
naming, not ours, but it costs time on every product entered. A relabel in our
view inheritance would fix it.

### ⚠️ 2.5 Two POS features break with no network
Both make a live server call with no offline fallback:

| Feature | File |
|---|---|
| Customer History popup | `static/src/overrides/customer_history.js:35` |
| Quotations — create, update, duplicate, list | `static/src/overrides/quotation.js` (3 calls), `quotation_picker.js:41` |

Everything else of ours survives offline: manager PIN (compared locally against
already-loaded hashes), min/max enforcement, order discounts, credit-limit
warnings, receipts.

---

## 3. Offline capability — what is actually true

Verified in `point_of_sale/static/src/app/services/data_service.js` and
`pos_store.js`.

**It works.** The till pings `/pos/ping` every two seconds, flips to offline mode
when that fails, keeps selling from data cached in IndexedDB, queues orders
locally, and pushes them automatically on reconnect — including across a page
refresh while still offline.

**It does not cover:**

- Opening a session. The first load must be online.
- The back office. Products, purchases, bills, reports all need the server.
- Invoices. They need a server-side sequence.
- The two features in 2.5.

**Three risks to plan around:**

1. **Stock can go negative.** Two tills offline at once can each sell the last
   piece. Both sync cleanly; stock lands at −1.
2. **Customer balances go stale.** Outstanding amounts are frozen at session
   load, so offline credit decisions are guesswork.
3. **The browser holds the only copy.** Clearing cache or switching machine
   before reconnecting loses queued sales. Staff must reconnect before closing
   a session.

⚠️ **The structural point.** Production runs on a remote Contabo VPS, so the till
reaches it over the *internet* and every internet outage is a POS outage. Offline
mode is the only cover. Running Odoo on a machine **inside the shop**, with the
VPS as replica or backup target, would make the counter depend only on the shop
LAN — turning internet loss from survivable into irrelevant. Worth costing out
before scaling to more registers.

---

## 4. The plan — customer & vendor requirements

From the requirements document: customer details, payment modes, order
discounts, purchaser payment history, vendor returns.

**Already delivered, no work needed:** order-level discounts with role limits,
manager PIN, reasons and audit log; the customer ledger with running balance;
Receive Payment; Khata Adjustment; the POS History tab.

### ▶ 4.1 Customer details — fill the gaps
- Customer **photo** in the POS quick-create form and the customer profile popup
  (`image_128` into `_load_pos_data_fields`; the backend form already has it).
- **Payments Received** button on the customer form — inbound `account.payment`
  for that partner.
- **Invoices** button — `account.move` (`out_invoice` / `out_refund`).
- Ledger list: show Date / Debit / Credit / Balance by default.
- **Print Khata** — a per-customer PDF statement with running balance.

### ▶ 4.2 Payment modes — one set everywhere
- Seed four journals + four POS payment methods: **Cash, Card Swipe,
  Bank/Online, Cheque**, so the same four appear at the till, on customer
  payments, on vendor payments and on owner transactions. Merge in the
  JazzCash/EasyPaisa work from `feature/jazzcash-easypaisa-payments`.
- `cheque_number` and `cheque_date` on `account.payment`, shown only for the
  Cheque journal.
- **Owner transactions** — capital in / drawings out, via an Owner partner tag
  and the same journals, reusing the `pos.retail.ledger.adjustment` pattern.

### ▶ 4.3 Vendor payment history
- **Vendor Ledger** button — mirror of the customer ledger against
  `liability_payable`, with running balance.
- **Pay Vendor** — pre-filled outbound payment.
- **Payment History** — every payment to that vendor with date and method.

### ▶ 4.4 Vendor returns
- **Return to Vendor** wizard: pick received lines, quantity and a mandatory
  reason (reuse `pos.retail.return.reason`) → creates the return picking **and**
  the vendor credit note in one dated step.
- **Vendor Returns** report: date, vendor, items, quantity, value, and whether
  the credit note is reconciled (the vendor is "safe").
- Vendor bill form and goods-receipt report: show per-line unit price, quantity,
  line total and the bill total clearly.

### ▶ 4.5 Offline hardening
Give Customer History and Quotations a graceful offline path — show a clear
"needs a connection" message rather than an error, and hide or disable the
buttons while `data.network.offline` is set.

### ▶ 4.6 Docs
Update `README.md` and `SETUP_CHECKLIST.md` once the above lands.

---

## 5. Open questions

1. Which branch should 4.1–4.6 be built on — this one, or a new
   `feature/customer-vendor-khata`?
2. Were the Murshid Store products already imported under the English names?
   (Decides rename-sheet vs re-import — see section 1.)
3. Add `Keelein` (nails) to the product sheet?
4. Is Minimum Selling Price meant to be a hard floor (finding 2.1)?
5. Wire up or remove `wholesale_price` (finding 2.2)?

---

## 6. Housekeeping

`static/src/backend/sidebar.js`, `sidebar.scss` and `sidebar.xml` carry
uncommitted changes from earlier work, unrelated to anything in this document.
They should be reviewed and committed or reverted before the next release so
they do not ride along unnoticed.
