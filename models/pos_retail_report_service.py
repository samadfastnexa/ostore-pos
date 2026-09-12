"""Shared report-data helpers used across pos_retail PDF reports.

Every report in the module follows the same pattern: the QWeb template calls
a method on the document model (e.g. ``doc.pos_retail_khata_lines()``) to
obtain rows, rather than querying from the template itself. This model
collects helper methods that more than one report needs.

Abstract: nothing is stored; subclasses inherit for convenience.
"""

from odoo import api, models


class PosRetailReportService(models.AbstractModel):
    _name = 'pos.retail.report.service'
    _description = 'POS Retail Report Service'

    @api.model
    def _get_ledger_lines(self, partner_ids, account_type, date_from=None, date_to=None):
        """Fetch ledger lines with running balance for the given partners.

        Args:
            partner_ids: list of res.partner ids
            account_type: 'asset_receivable' for customers, 'liability_payable' for vendors
            date_from: optional start date filter
            date_to: optional end date filter

        Returns:
            dict mapping partner_id to a list of dicts with keys:
            date, name, debit, credit, balance, move_name, transaction_type
        """
        domain = [
            ('account_id.account_type', '=', account_type),
            ('parent_state', '=', 'posted'),
            ('partner_id', 'in', partner_ids),
        ]
        if date_from:
            domain.append(('date', '>=', date_from))
        if date_to:
            domain.append(('date', '<=', date_to))

        lines = self.env['account.move.line'].search(domain, order='date, id')

        result = {}
        balances = {}  # running balance per (partner_id, company_id)
        for ml in lines:
            pid = ml.partner_id.id
            key = (pid, ml.company_id.id)
            prev = balances.get(key, 0.0)
            if account_type == 'asset_receivable':
                amount = ml.debit - ml.credit
            else:
                amount = ml.credit - ml.debit
            new_balance = prev + amount
            balances[key] = new_balance

            result.setdefault(pid, []).append({
                'date': ml.date,
                'name': ml.move_id.name or '',
                'debit': ml.debit,
                'credit': ml.credit,
                'amount': amount,
                'balance': new_balance,
                'origin': ml.move_id.invoice_origin or '',
                'reference': ml.move_id.ref or '',
            })
        return result
