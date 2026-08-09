# Flexible Pricing & Tax — configuration guide

Two halves make up flexible pricing in OStore:

| Need | How it works | Where |
|---|---|---|
| A price **range** per product, adjustable at the till | built by `pos_retail` | Product form + POS |
| **Different prices per customer type** (retail / wholesale / VIP …) | **native Odoo pricelists** | Sales → Pricelists |
| **Tax inclusive / exclusive / exempt** | **native Odoo taxes** | Accounting → Taxes |

Only the first needed code. The other two are configuration — this guide covers them.

---

## 1. The selling price range (per product)

On the product form, **General Information → Selling Price Range**:

| Field | Meaning |
|---|---|
| Cost (`standard_price`) | what you pay |
| Sales Price (`list_price`) | the **default** selling price |
| Minimum Selling Price | floor of the allowed range |
| Maximum Retail Price (`mrp`) | ceiling of the allowed range — usually the price printed on the pack |

Rules enforced:

- `Minimum ≤ Sales Price ≤ Maximum` is validated when saving the product.
- Leave a bound at **0** to leave that side unrestricted.
- At the till a cashier may sell **anywhere inside the range with no approval**.
- Outside the range a **manager PIN** is required (any employee whose *POS
  Discount Role* has *Can Approve*), plus a reason if that setting is on.
- The range is enforced **server-side as well**, so a tampered browser cannot
  post an out-of-range price without an approval on record.

Products with **no range** (both bounds 0, or min = max) are added instantly at
their standard price — scanning stays fast.

**Settings → Point of Sale → Flexible Pricing**
- *Allow Price Within Range* — turn the price popup on/off for this register.
- *Require Reason for Price Override* — force a reason on manager approvals.

Reasons are managed at **Point of Sale → Configuration → Price Reasons**.

---

## 2. Customer-type pricing = pricelists (no code)

Do **not** use the Minimum/Maximum Retail Price fields to model wholesale or VIP pricing. Those
are guard rails. Different prices for different customers are pricelists.

### The pricelists ship with the module

`data/pos_retail_pricelist_data.xml` creates six on install — **Retail,
Wholesale, Dealer, Distributor, VIP, Corporate** — in the company currency, and
attaches them to any register that has none configured yet.

They arrive **empty, with no rules**, which means every one of them currently
resolves to the product's own Sales Price. Installing the module therefore
changes nobody's price. Add rules per store once the commercial rates are
agreed: **Sales → Products → Pricelists** (enable *Pricelists* in Sales settings
first).

Two deliberate choices worth knowing:

- The shipped pricelists start at **sequence 11**. Core creates a `Default`
  pricelist at sequence 10 per company, and a customer with no pricelist of
  their own falls back to the lowest-sequence one — so `Default` stays the
  fallback and no existing customer is re-priced.
- The records are `noupdate="1"`, and the register wiring runs through an
  idempotent hook that skips any register already listing a pricelist. Rename
  them, add rules, delete the ones you do not sell to — a module upgrade will
  not undo it.

Each pricelist holds rules that can select on:

- a **single product**, a **product category**, or **everything**
- a **minimum quantity** (e.g. 10+ units gets the bulk price)
- a **date range** (`Start Date` / `End Date`) — this is how promotions work
- price computed as a **fixed price**, a **percentage discount**, or a
  **formula** based on the sales price or on cost

### Attach a pricelist to a customer

On the contact: **Sales & Purchase → Pricelist**.

In the POS, selecting that customer **re-prices the cart automatically**. Lines
whose price was set manually (via the price popup) are deliberately left alone —
a negotiated price is not overwritten by a pricelist change.

### Per branch / per register

**Settings → Point of Sale → Pricing**: set the register's *Default Pricelist*
and the list of *Available Pricelists*. The cashier can switch pricelist
mid-order with the built-in **Pricelist** button.

### Resolution order

1. the price entered in the price popup (manual) — always wins
2. the customer's pricelist
3. the register's default pricelist
4. the product's Sales Price

### Customer groups / membership

Odoo has no separate "customer group" pricing. Model it by assigning the same
pricelist to every customer in the group — the Membership Level field on the
contact is a convenient way to find them and bulk-assign.

---

## 3. Tax: inclusive, exclusive, exempt (no code)

Tax behaviour lives on the **tax record**, not on the product, so a product is
"tax inclusive" simply by carrying an inclusive tax.

**Accounting → Configuration → Taxes.** The field is *Included in Price*:

| Goal | Tax setup | Product setup |
|---|---|---|
| **Tax inclusive** — Rs 1000 on the shelf, Rs 1000 paid | tax with *Included in Price* = **Tax Included** | set that tax as Customer Tax |
| **Tax exclusive** — Rs 1000 + 16% = Rs 1160 | tax with *Included in Price* = **Tax Excluded** | set that tax as Customer Tax |
| **Tax exempt** | — | leave **Customer Taxes empty**, or use a 0% tax if the receipt should still show a tax line |

Set the company-wide default at **Settings → Accounting → Default Taxes**
(`Included in Price`); individual taxes can override it.

### Exempting a whole customer or branch

Use a **fiscal position** (Accounting → Configuration → Fiscal Positions) that
maps your normal tax to a 0% tax or to nothing. Assign it to the customer, or set
it as the register's default under **Settings → Point of Sale → Fiscal Position**.
The cashier can also switch it per order with the built-in Fiscal Position button.

### Receipt display

**Settings → Point of Sale** controls whether the POS shows tax-included or
tax-excluded prices on screen. The receipt always prints the line price, any
discount, the tax breakdown and the final total.

---

## 4. Reports

**Point of Sale → Reporting → Price Reports**

| Report | Shows |
|---|---|
| Price Analysis | average selling price, quantity and margin per product |
| Price Overrides | every sale made outside the allowed range, with manager and reason |
| Sold Below Default Price | lines sold under the standard price |
| Sold Above Default Price | lines sold over the standard price |
| Manager Price Overrides | grouped by approving manager |
| Price Adjustment Reasons | grouped by reason |

All six are the same data with different filters, so any of them can be
re-grouped by product, cashier, manager, reason or date, and exported.
