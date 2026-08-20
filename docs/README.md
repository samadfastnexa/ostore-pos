# POS Retail — documentation

Everything written about this project lives in this folder. The one exception is
the module's own `../README.md`, which stays at the module root because the
manifest points at it and GitHub and the Odoo Apps store both render it from
there.

| Document | What it covers | Read it when |
|---|---|---|
| [ROADMAP.md](ROADMAP.md) | Work outstanding, findings from the current build, open decisions | Planning what to build next |
| [SETUP_CHECKLIST.md](SETUP_CHECKLIST.md) | Week 0–1 configuration, step by step | Standing up a new store |
| [DEPLOYMENT.md](DEPLOYMENT.md) | Deploying to the aaPanel server, written from a real deployment | Pushing to production |
| [PRICING_AND_TAX.md](PRICING_AND_TAX.md) | How prices, price ranges and taxes fit together | Setting up prices or chasing a tax problem |
| [IMPORT_DATA.md](IMPORT_DATA.md) | The seven generic starter sheets for a hardware shop | Bulk-loading a fresh catalogue |
| [MURSHID_STORE_IMPORT.md](MURSHID_STORE_IMPORT.md) | The Murshid Store catalogue — 446 products, how it was built, what still needs answering | Importing or correcting that catalogue |

## Where the spreadsheets are

The two import documents describe files that are **not** in this folder. The
sheets themselves live at the project root, outside the module, because they are
one shop's data rather than part of the product:

```
import-data/                 seven generic starter sheets
import-data/murshid-store/   the Murshid Store catalogue
```

`IMPORT_DATA.md` and `MURSHID_STORE_IMPORT.md` were moved here on
19 August 2026, from `import-data/README.md` and
`import-data/murshid-store/README.md` respectively.
