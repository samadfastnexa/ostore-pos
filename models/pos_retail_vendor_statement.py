"""Vendor statement lines for the Vendor Statement PDF report.

Mirror of pos_retail_khata_lines() (customer receivable ledger) but for the
payable side: every posted entry on this vendor's payable accounts, with a
running balance showing what the shop owes them.
"""

from odoo import models


class ResPartner(models.Model):
    _inherit = 'res.partner'

    def pos_retail_vendor_statement_lines(self):
        """Chronological payable entries for this vendor with running balance.

        Returns a list of dicts with keys: date, name, debit, credit, balance.
        Debit = payments made TO the vendor (reduces what is owed).
        Credit = bills FROM the vendor (increases what is owed).
        Balance = running total of what the shop owes.
        """
        self.ensure_one()
        lines = self.env['account.move.line'].search([
            ('partner_id', '=', self.id),
            ('account_id.account_type', '=', 'liability_payable'),
            ('parent_state', '=', 'posted'),
        ], order='date, id')
        rows = []
        balance = 0.0
        for ml in lines:
            balance += (ml.credit - ml.debit)
            rows.append({
                'date': ml.date,
                'name': ml.move_id.name or '',
                'debit': ml.debit,
                'credit': ml.credit,
                'balance': balance,
            })
        return rows
