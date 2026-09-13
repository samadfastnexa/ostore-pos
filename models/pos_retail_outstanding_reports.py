from odoo import fields, models, tools


class PosRetailOutstandingCustomer(models.Model):
    """Report view for customers with an outstanding balance.
    Shows Total Credit (all time credit purchases), Total Paid, Outstanding Balance,
    and Last Transaction Date.
    """
    _name = 'pos.retail.outstanding.customer'
    _description = "Outstanding Customer Report"
    _auto = False
    _order = 'outstanding DESC, partner_id'

    partner_id = fields.Many2one('res.partner', string="Customer", readonly=True)
    company_id = fields.Many2one('res.company', string="Branch", readonly=True)
    total_credit = fields.Monetary(string="Total Credit", readonly=True, currency_field='currency_id')
    total_paid = fields.Monetary(string="Paid", readonly=True, currency_field='currency_id')
    outstanding = fields.Monetary(string="Outstanding", readonly=True, currency_field='currency_id')
    last_transaction_date = fields.Date(string="Last Transaction", readonly=True)
    currency_id = fields.Many2one('res.currency', readonly=True)
    status = fields.Selection([('unpaid', "Unpaid"), ('outstanding', "Outstanding")], string="Status", readonly=True)
    user_id = fields.Many2one('res.users', string="Salesperson", readonly=True)

    def init(self):
        tools.drop_view_if_exists(self.env.cr, self._table)
        self.env.cr.execute("""
            CREATE OR REPLACE VIEW %s AS (
                SELECT
                    row_number() OVER () AS id,
                    p.id AS partner_id,
                    p.company_id AS company_id,
                    p.user_id AS user_id,
                    COALESCE(c.currency_id, (SELECT currency_id FROM res_company ORDER BY id LIMIT 1)) AS currency_id,
                    COALESCE(SUM(CASE WHEN ml.debit > 0 THEN ml.debit ELSE 0 END), 0) AS total_credit,
                    COALESCE(SUM(CASE WHEN ml.credit > 0 THEN ml.credit ELSE 0 END), 0) AS total_paid,
                    COALESCE(SUM(ml.debit - ml.credit), 0) AS outstanding,
                    MAX(ml.date) AS last_transaction_date,
                    CASE 
                        WHEN COALESCE(SUM(CASE WHEN ml.credit > 0 THEN ml.credit ELSE 0 END), 0) = 0 THEN 'unpaid'
                        ELSE 'outstanding'
                    END AS status
                FROM res_partner p
                JOIN account_move_line ml ON ml.partner_id = p.id
                JOIN account_account a ON a.id = ml.account_id
                LEFT JOIN res_company c ON c.id = p.company_id
                WHERE a.account_type = 'asset_receivable'
                  AND ml.parent_state = 'posted'
                GROUP BY p.id, p.company_id, p.user_id, c.currency_id
                HAVING COALESCE(SUM(ml.debit - ml.credit), 0) > 0.005
            )
        """ % self._table)


class PosRetailOutstandingVendor(models.Model):
    """Report view for vendors with an outstanding payable balance."""
    _name = 'pos.retail.outstanding.vendor'
    _description = "Outstanding Vendor Report"
    _auto = False
    _order = 'outstanding DESC, partner_id'

    partner_id = fields.Many2one('res.partner', string="Vendor", readonly=True)
    company_id = fields.Many2one('res.company', string="Branch", readonly=True)
    total_credit = fields.Monetary(string="Total Purchases", readonly=True, currency_field='currency_id')
    total_paid = fields.Monetary(string="Paid", readonly=True, currency_field='currency_id')
    outstanding = fields.Monetary(string="Outstanding Payable", readonly=True, currency_field='currency_id')
    last_transaction_date = fields.Date(string="Last Transaction", readonly=True)
    currency_id = fields.Many2one('res.currency', readonly=True)
    status = fields.Selection([('unpaid', "Unpaid"), ('outstanding', "Outstanding")], string="Status", readonly=True)
    user_id = fields.Many2one('res.users', string="Salesperson", readonly=True)

    def init(self):
        tools.drop_view_if_exists(self.env.cr, self._table)
        self.env.cr.execute("""
            CREATE OR REPLACE VIEW %s AS (
                SELECT
                    row_number() OVER () AS id,
                    p.id AS partner_id,
                    p.company_id AS company_id,
                    p.user_id AS user_id,
                    COALESCE(c.currency_id, (SELECT currency_id FROM res_company ORDER BY id LIMIT 1)) AS currency_id,
                    COALESCE(SUM(CASE WHEN ml.credit > 0 THEN ml.credit ELSE 0 END), 0) AS total_credit,
                    COALESCE(SUM(CASE WHEN ml.debit > 0 THEN ml.debit ELSE 0 END), 0) AS total_paid,
                    COALESCE(SUM(ml.credit - ml.debit), 0) AS outstanding,
                    MAX(ml.date) AS last_transaction_date,
                    CASE 
                        WHEN COALESCE(SUM(CASE WHEN ml.debit > 0 THEN ml.debit ELSE 0 END), 0) = 0 THEN 'unpaid'
                        ELSE 'outstanding'
                    END AS status
                FROM res_partner p
                JOIN account_move_line ml ON ml.partner_id = p.id
                JOIN account_account a ON a.id = ml.account_id
                LEFT JOIN res_company c ON c.id = p.company_id
                WHERE a.account_type = 'liability_payable'
                  AND ml.parent_state = 'posted'
                GROUP BY p.id, p.company_id, p.user_id, c.currency_id
                HAVING COALESCE(SUM(ml.credit - ml.debit), 0) > 0.005
            )
        """ % self._table)
