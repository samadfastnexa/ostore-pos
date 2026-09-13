from odoo import api, fields, models, tools


class PosRetailOutstandingCustomer(models.Model):
    """One row per customer: what they owe RIGHT NOW.

    Shows Customer, Total Credit, Paid, Outstanding, Last Transaction, Due Date, and Status.
    Enables filtering by Customer, Salesperson, Branch, Customer Type, Due Date, and Outstanding amount,
    and sorting by Highest Outstanding, Oldest Outstanding, and Customer Name.
    """
    _name = 'pos.retail.outstanding.customer'
    _description = "Outstanding Customer Balances"
    _auto = False
    _order = 'outstanding desc, partner_id'
    _rec_name = 'partner_id'

    partner_id = fields.Many2one('res.partner', string="Customer", readonly=True)
    company_id = fields.Many2one('res.company', string="Branch", readonly=True)
    user_id = fields.Many2one('res.users', string="Salesperson", readonly=True)
    customer_type = fields.Selection(
        [('company', "Company"), ('individual', "Individual")],
        string="Customer Type", readonly=True)
    is_company = fields.Boolean(string="Is Company", readonly=True)
    currency_id = fields.Many2one('res.currency', readonly=True)
    total_credit = fields.Monetary(string="Total Credit", readonly=True, currency_field='currency_id')
    total_paid = fields.Monetary(string="Paid", readonly=True, currency_field='currency_id')
    outstanding = fields.Monetary(
        string="Outstanding", readonly=True, currency_field='currency_id',
        help="What this customer owes the shop as of their posted transactions at this branch.")
    last_transaction_date = fields.Date(string="Last Transaction", readonly=True)
    last_transaction_datetime = fields.Datetime(string="Last Transaction (Time)", readonly=True)
    oldest_unpaid_date = fields.Date(string="Oldest Outstanding Date", readonly=True)
    due_date = fields.Date(string="Due Date", readonly=True)
    status = fields.Selection(
        [('unpaid', "Unpaid"), ('outstanding', "Outstanding")],
        string="Status", readonly=True)
    age_days = fields.Integer(
        string="Days Since Last Transaction", compute='_compute_age_days',
        help="How long it has been since anything last moved on this customer's account.")

    @api.depends('last_transaction_date')
    def _compute_age_days(self):
        today = fields.Date.context_today(self)
        for rec in self:
            rec.age_days = (today - rec.last_transaction_date).days if rec.last_transaction_date else 0

    @api.model
    def pos_retail_ledger_summary(self, domain):
        """Cards for the Outstanding Customers list. Reuses PosRetailLedgerSummary widget."""
        records = self.search(domain or [])
        return {
            'total_outstanding': sum(records.mapped('outstanding')),
            'total_credit': sum(records.mapped('total_credit')),
            'total_paid': sum(records.mapped('total_paid')),
            'count': len(records),
            'currency_id': self.env.company.currency_id.id,
        }

    def init(self):
        tools.drop_view_if_exists(self.env.cr, self._table)
        self.env.cr.execute("""
            CREATE OR REPLACE VIEW %(table)s AS (
                SELECT
                    row_number() OVER () AS id,
                    p.id                    AS partner_id,
                    ml.company_id           AS company_id,
                    p.user_id               AS user_id,
                    p.is_company            AS is_company,
                    CASE WHEN p.is_company THEN 'company' ELSE 'individual' END AS customer_type,
                    COALESCE(c.currency_id, (SELECT currency_id FROM res_company ORDER BY id LIMIT 1)) AS currency_id,
                    COALESCE(SUM(CASE WHEN ml.debit > 0 THEN ml.debit ELSE 0 END), 0) AS total_credit,
                    COALESCE(SUM(CASE WHEN ml.credit > 0 THEN ml.credit ELSE 0 END), 0) AS total_paid,
                    COALESCE(SUM(ml.debit - ml.credit), 0) AS outstanding,
                    MAX(ml.date)            AS last_transaction_date,
                    MAX(ml.create_date)     AS last_transaction_datetime,
                    MIN(CASE WHEN ml.amount_residual > 0.005 AND ml.debit > 0 THEN ml.date ELSE NULL END) AS oldest_unpaid_date,
                    MIN(CASE WHEN ml.amount_residual > 0.005 AND ml.debit > 0 AND ml.date_maturity IS NOT NULL THEN ml.date_maturity ELSE NULL END) AS due_date,
                    CASE 
                        WHEN COALESCE(SUM(CASE WHEN ml.credit > 0 THEN ml.credit ELSE 0 END), 0) <= 0.005 THEN 'unpaid'
                        ELSE 'outstanding'
                    END AS status
                FROM res_partner p
                JOIN account_move_line ml ON ml.partner_id = p.id
                JOIN account_account a ON a.id = ml.account_id
                LEFT JOIN res_company c ON c.id = ml.company_id
                WHERE a.account_type = 'asset_receivable'
                  AND ml.parent_state = 'posted'
                GROUP BY p.id, ml.company_id, p.user_id, p.is_company, c.currency_id
                HAVING COALESCE(SUM(ml.debit - ml.credit), 0) > 0.005
            )
        """ % {'table': self._table})


class PosRetailOutstandingVendor(models.Model):
    """One row per supplier: what the shop owes them RIGHT NOW.

    Shows Vendor, Total Purchases, Paid, Outstanding Payable, Last Transaction, Due Date, and Status.
    Enables filtering by Vendor, Buyer/Salesperson, Branch, Vendor Type, Due Date, and Payable amount,
    and sorting by Highest Payable, Oldest Payable, and Vendor Name.
    """
    _name = 'pos.retail.outstanding.vendor'
    _description = "Outstanding Vendor Balances"
    _auto = False
    _order = 'outstanding desc, partner_id'
    _rec_name = 'partner_id'

    partner_id = fields.Many2one('res.partner', string="Vendor", readonly=True)
    company_id = fields.Many2one('res.company', string="Branch", readonly=True)
    user_id = fields.Many2one('res.users', string="Salesperson", readonly=True)
    vendor_type = fields.Selection(
        [('company', "Company"), ('individual', "Individual")],
        string="Vendor Type", readonly=True)
    is_company = fields.Boolean(string="Is Company", readonly=True)
    currency_id = fields.Many2one('res.currency', readonly=True)
    total_credit = fields.Monetary(string="Total Purchases", readonly=True, currency_field='currency_id')
    total_paid = fields.Monetary(string="Paid", readonly=True, currency_field='currency_id')
    outstanding = fields.Monetary(
        string="Outstanding Payable", readonly=True, currency_field='currency_id',
        help="What the shop owes this supplier as of posted transactions at this branch.")
    last_transaction_date = fields.Date(string="Last Transaction", readonly=True)
    last_transaction_datetime = fields.Datetime(string="Last Transaction (Time)", readonly=True)
    oldest_unpaid_date = fields.Date(string="Oldest Payable Date", readonly=True)
    due_date = fields.Date(string="Due Date", readonly=True)
    status = fields.Selection(
        [('unpaid', "Unpaid"), ('outstanding', "Outstanding")],
        string="Status", readonly=True)
    age_days = fields.Integer(
        string="Days Since Last Transaction", compute='_compute_age_days',
        help="How long it has been since anything last moved on this supplier's account.")

    @api.depends('last_transaction_date')
    def _compute_age_days(self):
        today = fields.Date.context_today(self)
        for rec in self:
            rec.age_days = (today - rec.last_transaction_date).days if rec.last_transaction_date else 0

    @api.model
    def pos_retail_ledger_summary(self, domain):
        """Cards for the Outstanding Vendors list. Reuses PosRetailLedgerSummary widget."""
        records = self.search(domain or [])
        return {
            'total_outstanding': sum(records.mapped('outstanding')),
            'total_credit': sum(records.mapped('total_credit')),
            'total_paid': sum(records.mapped('total_paid')),
            'count': len(records),
            'currency_id': self.env.company.currency_id.id,
        }

    def init(self):
        tools.drop_view_if_exists(self.env.cr, self._table)
        self.env.cr.execute("""
            CREATE OR REPLACE VIEW %(table)s AS (
                SELECT
                    row_number() OVER () AS id,
                    p.id                    AS partner_id,
                    ml.company_id           AS company_id,
                    p.user_id               AS user_id,
                    p.is_company            AS is_company,
                    CASE WHEN p.is_company THEN 'company' ELSE 'individual' END AS vendor_type,
                    COALESCE(c.currency_id, (SELECT currency_id FROM res_company ORDER BY id LIMIT 1)) AS currency_id,
                    COALESCE(SUM(CASE WHEN ml.credit > 0 THEN ml.credit ELSE 0 END), 0) AS total_credit,
                    COALESCE(SUM(CASE WHEN ml.debit > 0 THEN ml.debit ELSE 0 END), 0) AS total_paid,
                    COALESCE(SUM(ml.credit - ml.debit), 0) AS outstanding,
                    MAX(ml.date)            AS last_transaction_date,
                    MAX(ml.create_date)     AS last_transaction_datetime,
                    MIN(CASE WHEN ml.amount_residual < -0.005 AND ml.credit > 0 THEN ml.date ELSE NULL END) AS oldest_unpaid_date,
                    MIN(CASE WHEN ml.amount_residual < -0.005 AND ml.credit > 0 AND ml.date_maturity IS NOT NULL THEN ml.date_maturity ELSE NULL END) AS due_date,
                    CASE 
                        WHEN COALESCE(SUM(CASE WHEN ml.debit > 0 THEN ml.debit ELSE 0 END), 0) <= 0.005 THEN 'unpaid'
                        ELSE 'outstanding'
                    END AS status
                FROM res_partner p
                JOIN account_move_line ml ON ml.partner_id = p.id
                JOIN account_account a ON a.id = ml.account_id
                LEFT JOIN res_company c ON c.id = ml.company_id
                WHERE a.account_type = 'liability_payable'
                  AND ml.parent_state = 'posted'
                GROUP BY p.id, ml.company_id, p.user_id, p.is_company, c.currency_id
                HAVING COALESCE(SUM(ml.credit - ml.debit), 0) > 0.005
            )
        """ % {'table': self._table})
