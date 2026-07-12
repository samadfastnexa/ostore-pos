# POS Retail — Week 0–1 Configuration Checklist

Goal: stand up the MVP by **configuring standard Odoo apps** + the `pos_retail`
module. No extra code needed for anything in this document. Menu paths verified
against Odoo 19 source.

Legend: ☐ = do it · 🧩 = provided by `pos_retail` · ⚙️ = standard-app config · ⚠️ = known gap (needs custom code later)

---

## Week 0 — Install & baseline

### 0.1 Install the app stack
`pos_retail` now **depends on the whole stack**, so one command installs
everything (Point of Sale, Purchase, Accounting, Inventory, Loyalty, `pos_loyalty`,
`pos_discount`, `pos_hr`, `product_expiry` — all pulled transitively):

> Install command (your own terminal):
> `venv\Scripts\python.exe odoo\odoo-bin -c odoo.conf -d <db> -i pos_retail --stop-after-init`

☐ Run the command above against your target DB, then start Odoo normally.
☐ Verify in Apps that Point of Sale, Purchase, Coupons & Loyalty all show installed.

### 0.2 Company & POS basics
☐ Settings ▸ Companies — set store name, address, logo, currency (PKR), phone
☐ Point of Sale ▸ Configuration ▸ Settings — pick your POS ("Shop"), and enable:
- ⚙️ **Global Discounts** (`pos_module_pos_discount`) → cashier can apply an order-level %/fixed discount
- ⚙️ **Promotions, Coupons, Gift Card & Loyalty** (the `pos-loyalty` setting)
- ⚙️ **Bill Splitting / Multiple Payments** — split payment is native, just confirm
- ⚙️ Receipt header/footer text, "Print via" / customer barcode as needed

### 0.3 Units of Measure
☐ Settings ▸ Inventory ▸ enable **Units of Measure** → gives Kg / Piece / Liter
☐ Point of Sale ▸ Configuration ▸ Settings ▸ enable **Weighing scale** if selling by weight

---

## Week 1 — Products, Inventory, Vendors, Customers

### 1.1 Product foundations
☐ 🧩 **Brands**: Point of Sale ▸ Products ▸ **Product Brands** → create Nestlé, Coca-Cola, …
☐ ⚙️ **POS Categories**: Point of Sale ▸ Products ▸ Product Categories (Beverages, Snacks…)
☐ ⚙️ **Product Tags**: create tags (e.g. "Imported", "Halal")
☐ Create/import products with:
- `default_code` = **SKU**, `barcode` = EAN13/Code128
- **Cost** (standard_price) + **Sales Price** (list_price)
- **Unit of Measure** (Kg/Piece/Liter)
- 🧩 **Brand**, ⚙️ Category, ⚙️ Tags
- multiple images (main image + extra media on the product form)
- ☐ tick **Available in POS**
☐ ⚙️ **Variants**: Settings ▸ Sales ▸ enable Variants; add attributes (Size/Color) on a product
☐ ⚙️ **Expiry**: on a tracked product set Tracking = Lot/Serial, tick **Expiration Date** (product_expiry)

### 1.2 Inventory operations (all standard `stock`)
☐ ⚙️ **Stock In**: Inventory ▸ Operations ▸ Receipts (or via Purchase receipt)
☐ ⚙️ **Stock Out / Adjustment**: Inventory ▸ Operations ▸ Physical Inventory (count → apply)
☐ ⚙️ **Transfers**: Inventory ▸ Operations ▸ Transfers (needs 2+ locations/warehouses)
☐ ⚙️ **Damaged**: Inventory ▸ Operations ▸ Scrap → this is your "damaged products"
☐ ⚙️ **Reorder / Low-stock alert**: on product ▸ Reordering Rules → set Min/Max qty.
   Inventory ▸ Operations ▸ Replenishment shows items below minimum.
☐ ⚙️ **Expired**: Inventory ▸ Products ▸ Lots/Serials, filter by expiration; remove via Scrap

### 1.3 Vendors & Purchasing (standard `purchase` + `account`)
☐ ⚙️ Contacts ▸ create Vendor: name, company, phone, email, address, **Tax ID (VAT)**
☐ ⚙️ On vendor ▸ Sales & Purchase tab: **Payment Terms**, and Accounting tab: **Credit Limit**
☐ ⚙️ On each product ▸ Purchase tab: add **Vendor** (supplier info, price) → "product supplied by vendor"
☐ ⚙️ **Purchase Order** flow: Purchase ▸ Orders ▸ New → confirm → Receive → create Vendor Bill
☐ ⚙️ **Vendor Ledger**: Accounting ▸ Reporting ▸ Partner Ledger (filter the vendor) → outstanding balance
☐ ⚙️ **Purchase Reports**: Purchase ▸ Reporting

### 1.4 Customers, Loyalty & Membership
☐ ⚙️ Contacts (or POS "Customers") ▸ create customer: phone, email
☐ 🧩 On customer form (after Tags): set **Membership Level** (Bronze/Silver/Gold/VIP) + **Birthday**
☐ ⚙️ **Loyalty points**: Point of Sale ▸ Products ▸ Discount & Loyalty ▸ New ▸ type
   **Loyalty Cards** → earn X points per PKR, redeem "100 points = 100 PKR"
☐ ⚙️ **Credit balance / eWallet**: Point of Sale ▸ Products ▸ Gift cards & eWallet ▸ eWallet
☐ ⚙️ **Purchase history**: automatic — Customer form ▸ Sales/Point of Sale smart buttons

---

## Discounts & Offers — map each to a Loyalty program

**All of these are configured, not coded.** Point of Sale ▸ Products ▸
**Discount & Loyalty** ▸ New, then pick the program type:

| Your requirement | Program type | Rule → Reward |
|---|---|---|
| Milk 20% off (product discount) | Promotions | Rule: product = Milk → Reward: 20% discount |
| Order total 5000 → 10% off | Promotions | Rule: Min purchase 5000 → 10% discount on order |
| All Beverages 20% off (category) | Promotions | Rule: product category = Beverages → 20% discount |
| Buy 1 Coke Get 1 free (BOGO) | Buy X Get Y | Buy 1 Coke → get 1 Coke free |
| Buy 2, third 50% | Buy X Get Y | Buy 2 → reward 50% discount on next unit |
| Spend 5000 → free gift | Promotions | Rule: Min purchase 5000 → Reward: **Free Product** (the gift) |
| Coupon WELCOME100 | Coupons **or** Discount Code | Generate/print codes → discount on validation |
| 100 points = 100 PKR | Loyalty Cards | Redeem rule points→discount |
| Combo (Burger+Fries+Drink special price) | POS **Combo** product | Point of Sale ▸ Products ▸ Combo Choices, then a Combo product |
| VIP customers 5% off | **Pricelist** (recommended) | Create a "VIP" pricelist −5%, assign to VIP customers |
| Happy Hour 3–5 PM ⚠️ | — | ⚠️ **Gap**: loyalty/pricelists do date ranges, not time-of-day. Needs custom code (a scheduled activate/deactivate or a POS-side rule). Deferred. |

> Tip: every program has **Start/End Date** and can be limited to specific
> products, categories, customers-via-pricelist, and minimum amount/quantity.

---

## Payments

☐ ⚙️ **Cash** & **Bank/Card**: Point of Sale ▸ Configuration ▸ Payment Methods (exist by default)
☐ ⚙️ **Split payment**: native in POS — just add multiple payment lines
☐ 🔜 **JazzCash / EasyPaisa**: for MVP create **manual** payment methods
   (Payment Methods ▸ New, non-cash, no terminal) so cashiers can record them.
   Real API integration = later custom work.

## Receipts, Barcode & Labels
☐ ⚙️ Receipt logo/header/footer: Point of Sale ▸ Configuration ▸ Settings (Bills & Receipts)
☐ 🔜 Custom receipt (QR, return policy exact layout) = later `pos_retail` template
☐ ⚙️ **Print product labels**: Inventory/POS ▸ Products ▸ select ▸ Print ▸ Labels (Code128/EAN13)
☐ ⚙️ Scanner: any USB/Bluetooth scanner works as keyboard input — no config

## Phase 2 preview (standard apps)
☐ ⚙️ **Cashier login**: POS Settings ▸ enable **Employees can log in** (`pos_hr`) → PIN/badge
☐ ⚙️ **Cash control**: POS Settings ▸ enable **Cash Control** → open/close session with count & difference
☐ ⚙️ **Attendance / Leave**: install `hr_attendance`, `hr_holidays`
☐ 🔜 Cash-drawer variance **approval** workflow = later `pos_retail` code

---

## Definition of done (MVP demo-ready)
- [ ] Open a POS session, scan a product, apply a line + order discount, split-pay, print receipt
- [ ] One working promotion of each type above fires correctly in POS
- [ ] A customer earns & redeems loyalty points
- [ ] Purchase order → receipt → vendor bill, vendor ledger shows balance
- [ ] Low-stock replenishment lists an under-min product
- [ ] Brand, membership level & birthday visible and saved
