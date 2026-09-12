from odoo import api, fields, models, tools

# Not the same file as the stray, unregistered pos_retail_outstanding_reports.py
# left in this directory: that draft computes its own totals straight from
# account.move.line (getting company_id wrong -- the partner's own company,
# not the transaction's) and duplicates work the ledgers already do
# correctly. These two views instead read straight off
# pos.retail.customer.ledger.line / pos.retail.vendor.ledger.line, so there is
# exactly one place "how much does this partner currently owe" is computed,
# and the ledger's own running balance is never recomputed a second, possibly
# disagreeing, way.


class PosRetailOutstandingCustomer(models.Model):
    """One row per customer: what they owe RIGHT NOW, nothing else.

    "Right now" is the running balance carried by their most recent ledger
    entry (pos.retail.customer.ledger.line.balance_after), which is already a
    cumulative total across that customer's whole history at this branch --
    not a sum of this view's own rows, which would count every past
    transaction over again. The same DISTINCT ON (partner, branch) -- most
    recent date, then id, wins -- as the Python loop
    pos.retail.ledger.mixin.pos_retail_ledger_summary() already uses to work
    out the ledger's own balance card, so the two can never disagree.

    Only customers who have at least one ledger entry appear here. A
    customer who has never bought on credit, never had a refund and never
    made a payment has nothing to be "outstanding", so there is nothing to
    show.
    """
    _name = 'pos.retail.outstanding.customer'
    _description = "Outstanding Customer Balances"
    _auto = False
    _order = 'outstanding desc'
    _rec_name = 'partner_id'

    partner_id = fields.Many2one('res.partner', string="Customer", readonly=True)
    company_id = fields.Many2one('res.company', string="Branch", readonly=True)
    currency_id = fields.Many2one('res.currency', readonly=True)
    last_transaction_date = fields.Date(string="Last Transaction", readonly=True)
    last_transaction_datetime = fields.Datetime(string="Last Transaction (Time)", readonly=True)
    last_move_name = fields.Char(string="Last Invoice / Order No.", readonly=True)
    last_transaction_type = fields.Selection(
        [('sale', "Sale (invoice)"), ('pos_sale', "Sale on credit (till)"),
         ('refund', "Refund"), ('payment', "Payment received"),
         ('adjustment', "Khata adjustment")],
        string="Last Transaction Type", readonly=True)
    outstanding = fields.Monetary(
        string="Outstanding Balance", readonly=True, currency_field='currency_id',
        help="What this customer owes the shop as of their last transaction "
             "at this branch. Positive: they owe the shop. Negative: the "
             "shop owes them (an overpayment or an over-credited return).")
    age_days = fields.Integer(
        string="Days Since Last Transaction", compute='_compute_age_days',
        help="How long it has been since anything last moved on this "
             "customer's account -- a stale balance is as worth noticing as "
             "a large one.")

    @api.depends('last_transaction_date')
    def _compute_age_days(self):
        today = fields.Date.context_today(self)
        for rec in self:
            rec.age_days = (today - rec.last_transaction_date).days if rec.last_transaction_date else 0

    @api.model
    def pos_retail_ledger_summary(self, domain):
        """Cards for the Outstanding Customers list. Reuses the same
        PosRetailLedgerSummary widget the two full ledgers use (see
        ledger_summary.js), so the totals recompute for whatever is
        filtered exactly the same way theirs do -- but there is no "as of
        last transaction" subtlety to work around here: each row already
        IS one customer's current balance, so the total is a plain sum.
        """
        groups = self._read_group(domain, [], ['outstanding:sum', '__count'])
        total, count = groups[0] if groups else (0.0, 0)
        return {
            'total_outstanding': total or 0.0,
            'count': count or 0,
            'currency_id': self.env.company.currency_id.id,
        }

    def init(self):
        tools.drop_view_if_exists(self.env.cr, self._table)
        self.env.cr.execute("""
            CREATE OR REPLACE VIEW %(table)s AS (
                SELECT DISTINCT ON (l.partner_id, l.company_id)
                    l.id                    AS id,
                    l.partner_id            AS partner_id,
                    l.company_id            AS company_id,
                    l.currency_id           AS currency_id,
                    l.date                  AS last_transaction_date,
                    l.datetime              AS last_transaction_datetime,
                    l.move_name             AS last_move_name,
                    l.transaction_type      AS last_transaction_type,
                    l.balance_after         AS outstanding
                FROM pos_retail_customer_ledger_line l
                ORDER BY l.partner_id, l.company_id, l.date DESC, l.id DESC
            )
        """ % {'table': self._table})


class PosRetailOutstandingVendor(models.Model):
    """One row per supplier: what the shop owes them RIGHT NOW.

    Mirrors PosRetailOutstandingCustomer exactly, one balance sheet flipped:
    the source is pos.retail.vendor.ledger.line, and Outstanding is that
    supplier's Remaining Payable as of their most recent entry at this
    branch -- what a bill increases and a payment made brings back down.
    """
    _name = 'pos.retail.outstanding.vendor'
    _description = "Outstanding Vendor Balances"
    _auto = False
    _order = 'outstanding desc'
    _rec_name = 'partner_id'

    partner_id = fields.Many2one('res.partner', string="Vendor", readonly=True)
    company_id = fields.Many2one('res.company', string="Branch", readonly=True)
    currency_id = fields.Many2one('res.currency', readonly=True)
    last_transaction_date = fields.Date(string="Last Transaction", readonly=True)
    last_transaction_datetime = fields.Datetime(string="Last Transaction (Time)", readonly=True)
    last_move_name = fields.Char(string="Last Bill / Payment No.", readonly=True)
    last_transaction_type = fields.Selection(
        [('bill', "Purchase (bill)"), ('refund', "Vendor refund"),
         ('payment', "Payment made"), ('adjustment', "Adjustment")],
        string="Last Transaction Type", readonly=True)
    outstanding = fields.Monetary(
        string="Outstanding Balance", readonly=True, currency_field='currency_id',
        help="What the shop owes this supplier as of their last transaction "
             "at this branch. Positive: the shop owes them. Negative: they "
             "owe the shop (an overpayment or a vendor refund not yet used).")
    age_days = fields.Integer(
        string="Days Since Last Transaction", compute='_compute_age_days')

    @api.depends('last_transaction_date')
    def _compute_age_days(self):
        today = fields.Date.context_today(self)
        for rec in self:
            rec.age_days = (today - rec.last_transaction_date).days if rec.last_transaction_date else 0

    @api.model
    def pos_retail_ledger_summary(self, domain):
        """Cards for the Outstanding Vendors list. See the customer side's
        docstring above -- same reasoning, flipped to Payable."""
        groups = self._read_group(domain, [], ['outstanding:sum', '__count'])
        total, count = groups[0] if groups else (0.0, 0)
        return {
            'total_outstanding': total or 0.0,
            'count': count or 0,
            'currency_id': self.env.company.currency_id.id,
        }

    def init(self):
        tools.drop_view_if_exists(self.env.cr, self._table)
        self.env.cr.execute("""
            CREATE OR REPLACE VIEW %(table)s AS (
                SELECT DISTINCT ON (l.partner_id, l.company_id)
                    l.id                    AS id,
                    l.partner_id            AS partner_id,
                    l.company_id            AS company_id,
                    l.currency_id           AS currency_id,
                    l.date                  AS last_transaction_date,
                    l.datetime              AS last_transaction_datetime,
                    l.move_name             AS last_move_name,
                    l.transaction_type      AS last_transaction_type,
                    l.balance_after         AS outstanding
                FROM pos_retail_vendor_ledger_line l
                ORDER BY l.partner_id, l.company_id, l.date DESC, l.id DESC
            )
        """ % {'table': self._table})
