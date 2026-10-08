"""List contacts whose khata sits on the wrong side. READ-ONLY: writes nothing.

    Server:  bash scripts/run_check_ledger_sides.sh
    Local:   venv/Scripts/python.exe odoo/odoo-bin shell -c odoo.conf -d OStore \
                 --no-http < custom_addons/pos_retail/scripts/check_ledger_sides.py

The Customer Khata list shows every contact with a balance on a receivable
account; the Vendor list, every contact with a balance on a payable account.
Until pos_retail_ledger_sides.py, a vendor's form offered the customer's
"Adjust Khata" and "Receive Payment", so supplier balances were typed in on
the customer side. This prints, per branch:

  1. contacts in the CUSTOMER khata that look like vendors -- marked as a
     vendor, or with a vendor code / purchase orders / vendor bills, or with no
     sale at all behind the balance (only hand-made adjustments and payments)
     -- each with the entries that put them there;
  2. contacts in the VENDOR khata that look like customers, the same way.

Nothing is changed. Tell the developer which of the listed contacts really are
vendors (or customers) and those entries can be moved to the right ledger.

Optional: IMPORT_BRANCH (default: every branch).
"""

import os

BRANCH = os.environ.get('IMPORT_BRANCH', '').strip()
Line = env['account.move.line'].sudo()
Partner = env['res.partner'].sudo().with_context(active_test=False)
companies = env['res.company'].sudo().search([('child_ids', '=', False)] + ([('name', 'ilike', BRANCH)] if BRANCH else []))
money = lambda v: f"{v:,.2f}"


def kind(line):
    """What made this ledger line, in the shop's words."""
    move = line.move_id
    if move.move_type in ('out_invoice', 'out_refund', 'in_invoice', 'in_refund'):
        return {'out_invoice': 'sale invoice', 'out_refund': 'sale refund',
                'in_invoice': 'vendor bill', 'in_refund': 'vendor refund'}[move.move_type]
    payment = getattr(move, 'origin_payment_id', False) or getattr(move, 'payment_id', False)
    if payment:
        return 'payment RECEIVED' if payment.payment_type == 'inbound' else 'payment PAID OUT'
    if 'pos.order' in env and env['pos.order'].sudo().search_count([('account_move', '=', move.id)], limit=1):
        return 'till sale'
    if move.journal_id.type == 'general':
        return 'khata adjustment'
    return move.journal_id.name or 'entry'


def report(account_type, title, own_word, other_word):
    print(f"\n{'=' * 78}\n{title}\n{'=' * 78}")
    found = 0
    for company in companies:
        groups = Line._read_group(
            [('account_id.account_type', '=', account_type), ('parent_state', '=', 'posted'),
             ('company_id', '=', company.id), ('partner_id', '!=', False)],
            ['partner_id'], ['debit:sum', 'credit:sum'])
        for partner, debit, credit in groups:
            balance = (debit - credit) if account_type == 'asset_receivable' else (credit - debit)
            if abs(balance) < 0.005:
                continue
            partner = Partner.browse(partner.id)
            lines = Line.search([('partner_id', '=', partner.id), ('account_id.account_type', '=', account_type),
                                 ('parent_state', '=', 'posted'), ('company_id', '=', company.id)], order='date, id')
            kinds = [kind(l) for l in lines]
            reasons = []
            if account_type == 'asset_receivable':
                sales = sum(1 for k in kinds if k in ('sale invoice', 'till sale'))
                orders = env['pos.order'].sudo().search_count([('partner_id', '=', partner.id)]) if 'pos.order' in env else 0
                if partner.vendor_code:
                    reasons.append(f"has vendor code {partner.vendor_code}")
                if 'purchase.order' in env and env['purchase.order'].sudo().search_count([('partner_id', '=', partner.id)], limit=1):
                    reasons.append("has purchase orders")
                if Line.search_count([('partner_id', '=', partner.id), ('account_id.account_type', '=', 'liability_payable'),
                                      ('parent_state', '=', 'posted')], limit=1):
                    reasons.append("also has vendor-side entries")
                if not sales and not orders:
                    reasons.append("no sale behind the balance, only hand-made entries")
            else:
                bills = sum(1 for k in kinds if k == 'vendor bill')
                if not partner.supplier_rank:
                    reasons.append("not marked as a vendor")
                if not bills and 'pos.order' in env and env['pos.order'].sudo().search_count([('partner_id', '=', partner.id)], limit=1):
                    reasons.append("has till sales and no vendor bill")
            if not reasons:
                continue
            found += 1
            print(f"\n{partner.display_name}  (id {partner.id}, {company.name})")
            print(f"   {own_word} balance: {money(balance)}   | marked customer: {'yes' if partner.customer_rank else 'no'}"
                  f"   | marked vendor: {'yes' if partner.supplier_rank else 'no'}")
            print(f"   looks like a {other_word} because: " + "; ".join(reasons))
            for l, k in zip(lines, kinds):
                who = l.move_id.create_uid.name or ''
                print(f"     {l.date}  {l.move_id.name or '':18} {k:18} debit {money(l.debit):>14}  credit {money(l.credit):>14}"
                      f"  {(l.move_id.ref or l.name or '')[:44]}  [{who}]")
    if not found:
        print("  none")
    return found


print(f"branches checked: {companies.mapped('name')}")
a = report('asset_receivable', "1. IN THE CUSTOMER KHATA, BUT LOOKS LIKE A VENDOR", "customer-side", "vendor")
b = report('liability_payable', "2. IN THE VENDOR KHATA, BUT LOOKS LIKE A CUSTOMER", "vendor-side", "customer")
print(f"\n{'=' * 78}\nREAD-ONLY CHECK -- nothing was changed. {a} contact(s) in list 1, {b} in list 2.\n{'=' * 78}")
