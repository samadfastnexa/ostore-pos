"""Move a vendor's khata from the customer ledger to the vendor ledger, all rows at once.

    Server:  PARTNER_IDS="44,52" bash scripts/run_move_khata_to_vendor.sh            (check)
             PARTNER_IDS="44,52" APPLY=1 bash scripts/run_move_khata_to_vendor.sh    (move)

For contacts scripts/check_ledger_sides.py listed as vendors sitting in the
customer khata. It does for every adjustment and payment row of the contacts
you name exactly what the "To Vendor" button on the Customer Ledger does for one
row (models/pos_retail_ledger_corrections.py):

  * an adjustment ("owes more") becomes "the shop owes the vendor more";
  * a "payment received" becomes a payment MADE to the vendor, from the same
    cash or bank account on the same date -- which also puts the cash right;
  * once nothing is left on the customer side the contact is a vendor only.

Only the contacts in PARTNER_IDS are touched (the ids are printed by the
check). Sales, till entries and invoices are never moved; they are listed and
left where they are. WITHOUT APPLY=1 nothing is written.
"""

import os

from odoo.exceptions import UserError

APPLY = os.environ.get('APPLY', '').strip().lower() in ('1', 'true', 'yes')
IDS = [int(x) for x in os.environ.get('PARTNER_IDS', '').replace(' ', '').split(',') if x.isdigit()]

print()
print("=" * 78)
print("MOVE KHATA TO THE VENDOR LEDGER " + ("" if APPLY else "-- CHECK (nothing is written, APPLY=1 to move)"))
print("=" * 78)
if not IDS:
    raise SystemExit('Name the contacts to move: PARTNER_IDS="44,52" (the ids printed by '
                     'run_check_ledger_sides.sh). Nothing was changed.')

Partner = env['res.partner'].sudo().with_context(active_test=False)
Line = env['account.move.line'].sudo()
Ledger = env['pos.retail.customer.ledger.line'].sudo()
money = lambda v: f"{v:,.2f}"


def balances(partner):
    env.flush_all()
    env.invalidate_all()
    out = {}
    for account_type in ('asset_receivable', 'liability_payable'):
        grouped = Line._read_group([('partner_id', '=', partner.id), ('parent_state', '=', 'posted'),
                                    ('account_id.account_type', '=', account_type)],
                                   aggregates=('debit:sum', 'credit:sum'))
        debit, credit = grouped[0] if grouped else (0.0, 0.0)
        out[account_type] = (debit or 0.0) - (credit or 0.0)
    return out['asset_receivable'] + 0.0, -out['liability_payable'] + 0.0  # + 0.0: no "-0.00"


moved = failed = 0
for partner in Partner.browse(IDS).exists():
    customer_side, vendor_side = balances(partner)
    print(f"\n{partner.display_name}  (id {partner.id})")
    print(f"   now:   customer khata {money(customer_side)} | vendor khata {money(vendor_side)}"
          f" | marked customer {'yes' if partner.customer_rank else 'no'}, vendor {'yes' if partner.supplier_rank else 'no'}")
    if not partner.supplier_rank:
        print("   SKIPPED: not marked as a vendor. If he is one, press \"Also a Vendor\" on his form first.")
        continue
    rows = Ledger.search([('partner_id', '=', partner.id)], order='date, id')
    movable = rows.filtered(lambda r: r.transaction_type in ('adjustment', 'payment'))
    for row in rows:
        what = {'adjustment': "-> the shop owes the vendor " + ("more" if row.debit else "less"),
                'payment': "-> payment MADE to the vendor"}.get(row.transaction_type, "STAYS (a sale, not moved)")
        print(f"     {row.date}  {row.move_name or '':18} {row.transaction_type:11} {money(row.debit or row.credit):>14}"
              f"  {(row.reference or '')[:30]:30} {what}")
    if not APPLY or not movable:
        continue
    try:
        with env.cr.savepoint():
            for row in movable:
                row.action_move_to_other_ledger()
        customer_side, vendor_side = balances(partner)
        partner.invalidate_recordset()
        print(f"   after: customer khata {money(customer_side)} | vendor khata {money(vendor_side)}"
              f" | marked customer {'yes' if partner.customer_rank else 'no'}, vendor {'yes' if partner.supplier_rank else 'no'}")
        moved += 1
    except UserError as e:
        failed += 1
        print(f"   NOT MOVED, nothing changed for this contact: {e}")

missing = set(IDS) - set(Partner.browse(IDS).exists().ids)
if missing:
    print(f"\nno contact with id {sorted(missing)}")
print("\n" + "=" * 78)
if APPLY:
    env.cr.commit()
    print(f"Done: {moved} contact(s) moved to the vendor ledger" + (f", {failed} left unchanged (see above)" if failed else "") + ".")
else:
    print("CHECK ONLY -- nothing was written. Run again with APPLY=1 to move.")
print("=" * 78)
