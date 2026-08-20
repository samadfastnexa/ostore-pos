# POS Retail (`pos_retail`)

Custom Odoo 19 module that fills the gaps Odoo core does not cover for the retail
POS MVP. Everything else on the roadmap (inventory, purchasing, vendors,
promotions, loyalty, cash control) is delivered by **standard Odoo apps** — this
module only adds the missing pieces.

## What this module adds

| Feature | Model / Field |
|---|---|
| Product Brand | new model `product.brand`; `brand_id` on `product.template` |
| Customer birthday | `birthday` on `res.partner` |
| Membership levels | new model `pos.membership.level`; `membership_level_id` on `res.partner` (Bronze/Silver/Gold/VIP seeded) |
| POS availability | `brand_id`, `birthday`, `membership_level_id` added to POS data loading |

## Menus

- **Point of Sale → Products → Product Brands**
- **Point of Sale → Configuration → Membership Levels** (managers)
- Brand field: on the product form (after Category) + group-by in product search
- Birthday & Membership: on the contact form (after Tags)

## Install / upgrade

The module lives in `custom_addons/`, already added to `addons_path` in
`odoo.conf`. Run Odoo in your **own** terminal:

```powershell
# First install (creates/updates the module in DB <your_db>)
venv\Scripts\python.exe odoo\odoo-bin -c odoo.conf -d <your_db> -i pos_retail --stop-after-init

# After code changes, upgrade:
venv\Scripts\python.exe odoo\odoo-bin -c odoo.conf -d <your_db> -u pos_retail --stop-after-init

# Then run normally:
venv\Scripts\python.exe odoo\odoo-bin -c odoo.conf
```

`pos_retail` depends on the full MVP stack — `point_of_sale`, `contacts`,
`pos_loyalty`, `pos_discount`, `pos_hr`, `product_expiry`, `purchase` — so a single
`-i pos_retail` installs everything (Sales, Inventory, Accounting, Loyalty are
pulled transitively).

See [docs/SETUP_CHECKLIST.md](docs/SETUP_CHECKLIST.md) for the full Week 0–1
configuration checklist (maps every discount/offer to a standard Loyalty program).

See [docs/ROADMAP.md](docs/ROADMAP.md) for the work currently outstanding and
the findings behind it — open decisions on pricing, offline behaviour and the
customer/vendor ledger features still to build.

## Roadmap (built on top of this scaffold)

1. Branded POS dashboard (OWL) — daily/monthly sales, top products, refunds
2. JazzCash / EasyPaisa payment methods (manual first, API later)
3. Custom receipt template (logo, QR, return policy, footer)
4. Barcode label layout
5. Cash-drawer variance approval (Phase 2)

Promotions/offers, discounts, coupons and loyalty points are configured through
the standard **Loyalty** app (`loyalty` + `pos_loyalty`) — no code required.
