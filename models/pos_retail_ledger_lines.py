from odoo import api, fields, models, tools

# SQL shared between the two ledgers for the columns the shop asked for on
# top of the running balance: Total Amount, Paid Amount, Remaining Balance,
# Payment Status and Payment History for a transaction that IS a debt (a
# sale, a bill, a refund) -- never for a payment or an adjustment, neither of
# which is itself something owed.
#
# Read from Odoo's own reconciliation, not recomputed. ml.balance is the
# transaction's original amount and never changes; ml.amount_residual is
# what Odoo's reconciliation engine still has unmatched on that exact line,
# and it moves to zero as payments are reconciled against it -- which is
# also why nothing here has to listen for a payment being made. Paid Amount
# is simply the difference, so "manually entered" is not a way this can go
# wrong: there is nowhere to type it.
_POS_RETAIL_STATUS_SQL_TEMPLATE = """
    CASE WHEN b.transaction_type IN ({debt_types})
         THEN b.abs_total END                                           AS total_amount,
    CASE WHEN b.transaction_type IN ({debt_types})
         THEN GREATEST(b.abs_total - b.abs_residual, 0) END              AS paid_amount,
    CASE WHEN b.transaction_type IN ({debt_types})
         THEN GREATEST(b.abs_residual, 0) END                            AS balance_amount,
    CASE
        WHEN b.transaction_type NOT IN ({debt_types}) THEN NULL
        WHEN b.abs_residual <= 0.005 THEN 'paid'
        WHEN b.abs_total - b.abs_residual <= 0.005 THEN 'unpaid'
        ELSE 'partial'
    END                                                                  AS payment_status,
    CASE WHEN b.transaction_type IN ({debt_types})
         THEN b.due_date END                                             AS due_date,
    CASE WHEN b.transaction_type IN ({debt_types})
         THEN b.payment_history END                                     AS payment_history,
"""

# Columns every "base" CTE must expose for the block above to compile:
# ml.balance and ml.amount_residual (as abs_total / abs_residual), the move's
# due date, and a correlated string of whatever has been reconciled against
# this exact line. Appended into each ledger's own base CTE.
_POS_RETAIL_STATUS_BASE_SQL = """
                        , ABS(ml.balance)                     AS abs_total
                        , ABS(ml.amount_residual)              AS abs_residual
                        , m.invoice_date_due                  AS due_date
                        , (SELECT string_agg(
                               to_char(other_m.date, 'YYYY-MM-DD') || ': ' ||
                               trim(to_char(pr.amount, 'FM999,999,999.00')) ||
                               ' (' || COALESCE(
                                   -- oj.name is a TRANSLATED field, stored as
                                   -- jsonb ({"en_US": "Cash"}), while
                                   -- account_move.name is a plain varchar; a
                                   -- raw COALESCE across the two types is
                                   -- what Postgres refused. en_US first
                                   -- since that is this shop's language, then
                                   -- whichever translation exists at all
                                   -- rather than showing nothing.
                                   oj.name ->> 'en_US',
                                   (SELECT v FROM jsonb_each_text(oj.name) AS t(k, v) LIMIT 1),
                                   other_m.name, '-'
                               ) || ')',
                               '; ' ORDER BY other_m.date, pr.id)
                             FROM account_partial_reconcile pr
                             JOIN account_move_line other_ml
                                  ON other_ml.id = CASE WHEN pr.debit_move_id = ml.id THEN pr.credit_move_id
                                                         WHEN pr.credit_move_id = ml.id THEN pr.debit_move_id END
                             JOIN account_move other_m ON other_m.id = other_ml.move_id
                             LEFT JOIN account_journal oj ON oj.id = other_m.journal_id
                            WHERE pr.debit_move_id = ml.id OR pr.credit_move_id = ml.id
                          )                                    AS payment_history
"""


class PosRetailLedgerMixin(models.AbstractModel):
    """What the two ledgers share: the summary cards, and nothing else.

    The customer and vendor ledgers are deliberately separate models over
    separate accounts, with separate columns, filters and totals. They never
    share rows. The only thing they have in common is HOW the "current
    balance" card is worked out, so that one piece lives here.
    """
    _name = 'pos.retail.ledger.mixin'
    _description = "Ledger summary helper"

    # Fields summed straight into cards, in card order, per ledger.
    _pos_retail_summary_sums = ()

    @api.model
    def pos_retail_ledger_summary(self, domain):
        """The figures for the cards above the ledger, for the current filters.

        The sums are plain: add up the column over the rows on screen.

        The balance card is not a sum, and a sum would be wrong. Adding up
        every row's running balance counts each customer's history over and
        over. The balance that matters is each partner's balance AS OF THEIR
        LAST TRANSACTION in the filtered range, added across partners -- so a
        date filter reads as "what was owed at the end of that period", which
        is the question a ledger is asked.
        """
        totals = {}
        if self._pos_retail_summary_sums:
            groups = self._read_group(
                domain, [], ['%s:sum' % f for f in self._pos_retail_summary_sums] + ['__count'])
            row = groups[0] if groups else (0,) * (len(self._pos_retail_summary_sums) + 1)
            for name, value in zip(self._pos_retail_summary_sums, row):
                totals[name] = value or 0.0
            totals['count'] = row[-1] if groups else 0

        latest = {}
        # Newest first, so the first row seen for each partner and branch is
        # their last transaction in range. Fetches three small columns, which
        # stays cheap at a shop's volumes while being right about ordering in a
        # way max(id) would not be: an entry dated earlier but posted later has
        # a higher id and the wrong balance.
        for rec in self.search_read(domain, ['partner_id', 'company_id', 'balance_after'],
                                    order='date desc, id desc'):
            key = (rec['partner_id'] and rec['partner_id'][0], rec['company_id'] and rec['company_id'][0])
            if key not in latest:
                latest[key] = rec['balance_after'] or 0.0
        totals['balance'] = sum(latest.values())
        totals['partner_count'] = len({k[0] for k in latest})
        totals['currency_id'] = self.env.company.currency_id.id
        return totals


class PosRetailCustomerLedgerLine(models.Model):
    """Money customers owe the shop, and money they have paid it.

    One row per posted entry on a customer's receivable account: an invoiced
    sale, a sale on credit at the till, a refund, a payment received, or a
    khata adjustment. The same source as Odoo's own Partner Ledger and the
    customer's Outstanding Balance, read through a friendlier lens.

    Only receivable accounts. Nothing here ever touches a payable account,
    so a supplier can never appear in this ledger and a vendor bill can
    never move a customer's balance. The vendor side is its own model.

    Previous and Remaining Balance are running totals computed per customer
    and branch across that customer's WHOLE history, not across whatever
    happens to be on screen. That is what makes them correct in a list mixing
    many customers, which Odoo's own running-balance column is not, and it
    means a date filter still shows the true balance before and after each
    row rather than one restarted from zero at the filter's start.

    Payment Status is a second, narrower question about the SAME row: not
    "what does the shop's whole relationship with this customer look like",
    but "has this one sale itself been settled". A sale can sit at Balance
    for weeks while the running balance above moves for unrelated reasons --
    another sale, another refund -- so the two figures are meant to disagree
    sometimes, and both are told plainly rather than only one being shown.
    """
    _name = 'pos.retail.customer.ledger.line'
    _inherit = 'pos.retail.ledger.mixin'
    _description = "Customer Ledger Line"
    _auto = False
    _order = 'date desc, id desc'
    _rec_name = 'move_name'
    _pos_retail_summary_sums = ('sale_amount', 'payment_received', 'refund_amount', 'discount_amount')

    date = fields.Date(string="Date", readonly=True)
    datetime = fields.Datetime(string="Date & Time", readonly=True)
    partner_id = fields.Many2one('res.partner', string="Customer", readonly=True)
    move_id = fields.Many2one('account.move', string="Entry", readonly=True)
    move_name = fields.Char(string="Invoice / Order No.", readonly=True)
    origin = fields.Char(string="Source Document", readonly=True)
    transaction_type = fields.Selection(
        [('sale', "Sale (invoice)"), ('pos_sale', "Sale on credit (till)"),
         ('refund', "Refund"), ('payment', "Payment received"),
         ('adjustment', "Khata adjustment")],
        string="Transaction Type", readonly=True)

    sale_amount = fields.Monetary(string="Sale Amount", readonly=True, currency_field='currency_id')
    payment_received = fields.Monetary(string="Payment Received", readonly=True, currency_field='currency_id')
    refund_amount = fields.Monetary(string="Refund", readonly=True, currency_field='currency_id')
    discount_amount = fields.Monetary(
        string="Discount", readonly=True, currency_field='currency_id',
        help="Discount given on this invoice: line discounts plus any discount "
             "line. Already taken off the Sale Amount; shown so it can be seen.")
    debit = fields.Monetary(string="Debit", readonly=True, currency_field='currency_id',
                            help="Increases what the customer owes.")
    credit = fields.Monetary(string="Credit", readonly=True, currency_field='currency_id',
                             help="Decreases what the customer owes.")
    amount = fields.Monetary(string="Transaction Amount", readonly=True, currency_field='currency_id',
                             help="Debit minus credit: what this one entry did to the balance.")
    balance_before = fields.Monetary(string="Previous Balance", readonly=True, currency_field='currency_id')
    balance_after = fields.Monetary(string="Remaining Outstanding", readonly=True, currency_field='currency_id',
                                    help="What the customer owed after this entry.")
    currency_id = fields.Many2one('res.currency', readonly=True)

    payment_journal_id = fields.Many2one(
        'account.journal', string="Payment Method", readonly=True,
        help="Where a payment went: cash, bank, a mobile wallet. Blank on sales "
             "and refunds, which are not payments.")
    user_id = fields.Many2one('res.users', string="Cashier / User", readonly=True)
    salesperson_id = fields.Many2one('res.users', string="Salesperson", readonly=True)
    company_id = fields.Many2one('res.company', string="Branch", readonly=True)
    reference = fields.Char(string="Reference / Notes", readonly=True)

    # Whether THIS ONE transaction has been settled, worked out from what has
    # actually been reconciled against it -- never typed in. A sale for
    # 10,000 with 6,000 reconciled against it is Balance, automatically, and
    # only moves to Paid when the remaining 4,000 is matched by a payment.
    total_amount = fields.Monetary(
        string="Total Amount", readonly=True, currency_field='currency_id',
        help="The full amount of this transaction, unaffected by how much of "
             "it has since been paid. Blank on payments and adjustments, "
             "which are not themselves a debt to track.")
    paid_amount = fields.Monetary(
        string="Paid Amount", readonly=True, currency_field='currency_id',
        help="How much of this transaction has been reconciled against a "
             "payment so far.")
    balance_amount = fields.Monetary(
        string="Remaining Balance", readonly=True, currency_field='currency_id',
        help="Total Amount minus Paid Amount.")
    payment_status = fields.Selection(
        [('unpaid', "Unpaid / Outstanding"), ('partial', "Balance / Partial Payment"),
         ('paid', "Paid")],
        string="Payment Status", readonly=True,
        help="Paid when nothing is left owing on this transaction. Unpaid / "
             "Outstanding when nothing has been paid against it yet. Balance "
             "/ Partial Payment when some has, but not all. Blank on a "
             "payment or an adjustment row.")
    due_date = fields.Date(string="Due Date", readonly=True)
    payment_history = fields.Char(
        string="Payment History", readonly=True,
        help="Every payment matched against this transaction so far, oldest "
             "first: date, amount and method.")

    def init(self):
        tools.drop_view_if_exists(self.env.cr, self._table)
        debt_types = "'sale', 'pos_sale', 'refund'"
        self.env.cr.execute("""
            CREATE OR REPLACE VIEW %(table)s AS (
                WITH base AS (
                    SELECT
                        ml.id                               AS id,
                        ml.date                             AS date,
                        ml.create_date                      AS datetime,
                        ml.partner_id                       AS partner_id,
                        m.id                                AS move_id,
                        m.name                              AS move_name,
                        m.invoice_origin                    AS origin,
                        CASE
                            WHEN m.move_type = 'out_invoice' THEN 'sale'
                            WHEN m.move_type = 'out_refund'  THEN 'refund'
                            WHEN m.origin_payment_id IS NOT NULL
                              OR m.statement_line_id IS NOT NULL THEN 'payment'
                            WHEN EXISTS (SELECT 1 FROM pos_session s WHERE s.move_id = m.id)
                                THEN CASE WHEN ml.debit > 0 THEN 'pos_sale' ELSE 'payment' END
                            WHEN j.type IN ('cash', 'bank') THEN 'payment'
                            ELSE 'adjustment'
                        END                                 AS transaction_type,
                        ml.debit                            AS debit,
                        ml.credit                           AS credit,
                        ml.debit - ml.credit                AS amount,
                        ml.company_currency_id              AS currency_id,
                        m.invoice_user_id                   AS salesperson_id,
                        COALESCE(m.invoice_user_id, ml.create_uid) AS user_id,
                        ml.company_id                       AS company_id,
                        NULLIF(COALESCE(NULLIF(m.ref, ''), ml.name), '') AS reference,
                        j.id                                AS journal_id,
                        j.type                              AS journal_type,
                        m.move_type                         AS move_type,
                        ROW_NUMBER() OVER (PARTITION BY m.id ORDER BY ml.id) AS rn
                        %(status_base)s
                    FROM account_move_line ml
                    JOIN account_move m     ON m.id = ml.move_id
                    JOIN account_account a  ON a.id = ml.account_id
                    JOIN account_journal j  ON j.id = m.journal_id
                    WHERE a.account_type = 'asset_receivable'
                      AND ml.parent_state = 'posted'
                      AND ml.partner_id IS NOT NULL
                )
                SELECT
                    b.id, b.date, b.datetime, b.partner_id, b.move_id, b.move_name,
                    b.origin, b.transaction_type, b.debit, b.credit, b.amount,
                    b.currency_id, b.salesperson_id, b.user_id, b.company_id, b.reference,
                    CASE WHEN b.transaction_type IN ('sale', 'pos_sale') THEN b.debit ELSE 0 END AS sale_amount,
                    CASE WHEN b.transaction_type = 'payment' THEN b.credit ELSE 0 END  AS payment_received,
                    CASE WHEN b.transaction_type = 'refund' THEN b.credit ELSE 0 END   AS refund_amount,
                    CASE WHEN b.transaction_type = 'payment' THEN b.journal_id END     AS payment_journal_id,
                    CASE WHEN b.rn = 1 AND b.move_type IN ('out_invoice', 'out_refund') THEN (
                        SELECT COALESCE(SUM(l2.price_unit * l2.quantity * l2.discount / 100.0), 0)
                             + COALESCE(SUM(CASE WHEN l2.price_subtotal < 0
                                                 THEN -l2.price_subtotal ELSE 0 END), 0)
                          FROM account_move_line l2
                         WHERE l2.move_id = b.move_id AND l2.display_type = 'product'
                    ) ELSE 0 END                                                        AS discount_amount,
                    %(status_cols)s
                    SUM(b.amount) OVER (
                        PARTITION BY b.partner_id, b.company_id
                        ORDER BY b.date, b.id
                        ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
                    ) - b.amount                                                        AS balance_before,
                    SUM(b.amount) OVER (
                        PARTITION BY b.partner_id, b.company_id
                        ORDER BY b.date, b.id
                        ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
                    )                                                                   AS balance_after
                FROM base b
            )
        """ % {
            'table': self._table,
            'status_base': _POS_RETAIL_STATUS_BASE_SQL,
            'status_cols': _POS_RETAIL_STATUS_SQL_TEMPLATE.format(debt_types=debt_types),
        })


class PosRetailVendorLedgerLine(models.Model):
    """Money the shop owes suppliers, and money it has paid them.

    One row per posted entry on a supplier's payable account: a vendor bill,
    a payment made, a vendor credit note, or a manual adjustment.

    Only payable accounts. No receivable line ever appears here, so no
    customer, sale or customer payment can move a supplier's balance. The
    signs are the payable side's own: a bill INCREASES what the shop owes, so
    Remaining Payable goes up on a bill and down on a payment, which is how
    anybody paying suppliers already thinks about it.

    Payment Status works the same way as on the customer ledger, and is
    worked out the same way: from what Odoo's reconciliation engine has
    actually matched against a bill or a vendor refund, never typed in.
    """
    _name = 'pos.retail.vendor.ledger.line'
    _inherit = 'pos.retail.ledger.mixin'
    _description = "Vendor Ledger Line"
    _auto = False
    _order = 'date desc, id desc'
    _rec_name = 'move_name'
    _pos_retail_summary_sums = ('purchase_amount', 'payment_made', 'refund_amount')

    date = fields.Date(string="Date", readonly=True)
    datetime = fields.Datetime(string="Date & Time", readonly=True)
    partner_id = fields.Many2one('res.partner', string="Vendor", readonly=True)
    move_id = fields.Many2one('account.move', string="Entry", readonly=True)
    move_name = fields.Char(string="Bill / Payment No.", readonly=True)
    origin = fields.Char(string="Purchase Order", readonly=True,
                         help="The purchase order the bill was raised from, where there is one.")
    transaction_type = fields.Selection(
        [('bill', "Purchase (bill)"), ('refund', "Vendor refund"),
         ('payment', "Payment made"), ('adjustment', "Adjustment")],
        string="Transaction Type", readonly=True)

    purchase_amount = fields.Monetary(string="Purchase Amount", readonly=True, currency_field='currency_id')
    payment_made = fields.Monetary(string="Payment Made", readonly=True, currency_field='currency_id')
    refund_amount = fields.Monetary(string="Vendor Refund", readonly=True, currency_field='currency_id')
    debit = fields.Monetary(string="Debit", readonly=True, currency_field='currency_id',
                            help="Decreases what the shop owes this supplier.")
    credit = fields.Monetary(string="Credit", readonly=True, currency_field='currency_id',
                             help="Increases what the shop owes this supplier.")
    amount = fields.Monetary(string="Transaction Amount", readonly=True, currency_field='currency_id',
                             help="Credit minus debit: what this one entry did to what is owed.")
    balance_before = fields.Monetary(string="Previous Balance", readonly=True, currency_field='currency_id')
    balance_after = fields.Monetary(string="Remaining Payable", readonly=True, currency_field='currency_id',
                                    help="What the shop owed this supplier after this entry.")
    currency_id = fields.Many2one('res.currency', readonly=True)

    payment_journal_id = fields.Many2one(
        'account.journal', string="Payment Method", readonly=True,
        help="Where a payment came from: cash, bank, a mobile wallet. Blank on "
             "bills and credit notes.")
    user_id = fields.Many2one('res.users', string="Staff / User", readonly=True)
    company_id = fields.Many2one('res.company', string="Branch", readonly=True)
    reference = fields.Char(string="Reference / Notes", readonly=True)

    total_amount = fields.Monetary(
        string="Total Amount", readonly=True, currency_field='currency_id',
        help="The full amount of this bill or vendor refund, unaffected by "
             "how much has since been paid. Blank on payments and "
             "adjustments, which are not themselves a debt to track.")
    paid_amount = fields.Monetary(
        string="Paid Amount", readonly=True, currency_field='currency_id',
        help="How much of this transaction has been reconciled against a "
             "payment so far.")
    balance_amount = fields.Monetary(
        string="Remaining Balance", readonly=True, currency_field='currency_id',
        help="Total Amount minus Paid Amount.")
    payment_status = fields.Selection(
        [('unpaid', "Unpaid / Outstanding"), ('partial', "Balance / Partial Payment"),
         ('paid', "Paid")],
        string="Payment Status", readonly=True,
        help="Paid when nothing is left owing on this transaction. Unpaid / "
             "Outstanding when nothing has been paid against it yet. Balance "
             "/ Partial Payment when some has, but not all. Blank on a "
             "payment or an adjustment row.")
    due_date = fields.Date(string="Due Date", readonly=True)
    payment_history = fields.Char(
        string="Payment History", readonly=True,
        help="Every payment matched against this transaction so far, oldest "
             "first: date, amount and method.")

    def init(self):
        tools.drop_view_if_exists(self.env.cr, self._table)
        debt_types = "'bill', 'refund'"
        self.env.cr.execute("""
            CREATE OR REPLACE VIEW %(table)s AS (
                WITH base AS (
                    SELECT
                        ml.id                               AS id,
                        ml.date                             AS date,
                        ml.create_date                      AS datetime,
                        ml.partner_id                       AS partner_id,
                        m.id                                AS move_id,
                        m.name                              AS move_name,
                        m.invoice_origin                    AS origin,
                        CASE
                            WHEN m.move_type = 'in_invoice' THEN 'bill'
                            WHEN m.move_type = 'in_refund'  THEN 'refund'
                            WHEN m.origin_payment_id IS NOT NULL
                              OR m.statement_line_id IS NOT NULL
                              OR j.type IN ('cash', 'bank') THEN 'payment'
                            ELSE 'adjustment'
                        END                                 AS transaction_type,
                        ml.debit                            AS debit,
                        ml.credit                           AS credit,
                        ml.credit - ml.debit                AS amount,
                        ml.company_currency_id              AS currency_id,
                        COALESCE(m.invoice_user_id, ml.create_uid) AS user_id,
                        ml.company_id                       AS company_id,
                        NULLIF(COALESCE(NULLIF(m.ref, ''), ml.name), '') AS reference,
                        j.id                                AS journal_id
                        %(status_base)s
                    FROM account_move_line ml
                    JOIN account_move m     ON m.id = ml.move_id
                    JOIN account_account a  ON a.id = ml.account_id
                    JOIN account_journal j  ON j.id = m.journal_id
                    WHERE a.account_type = 'liability_payable'
                      AND ml.parent_state = 'posted'
                      AND ml.partner_id IS NOT NULL
                )
                SELECT
                    b.id, b.date, b.datetime, b.partner_id, b.move_id, b.move_name,
                    b.origin, b.transaction_type, b.debit, b.credit, b.amount,
                    b.currency_id, b.user_id, b.company_id, b.reference,
                    CASE WHEN b.transaction_type = 'bill'    THEN b.credit ELSE 0 END AS purchase_amount,
                    CASE WHEN b.transaction_type = 'payment' THEN b.debit  ELSE 0 END AS payment_made,
                    CASE WHEN b.transaction_type = 'refund'  THEN b.debit  ELSE 0 END AS refund_amount,
                    CASE WHEN b.transaction_type = 'payment' THEN b.journal_id END     AS payment_journal_id,
                    %(status_cols)s
                    SUM(b.amount) OVER (
                        PARTITION BY b.partner_id, b.company_id
                        ORDER BY b.date, b.id
                        ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
                    ) - b.amount                                                        AS balance_before,
                    SUM(b.amount) OVER (
                        PARTITION BY b.partner_id, b.company_id
                        ORDER BY b.date, b.id
                        ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
                    )                                                                   AS balance_after
                FROM base b
            )
        """ % {
            'table': self._table,
            'status_base': _POS_RETAIL_STATUS_BASE_SQL,
            'status_cols': _POS_RETAIL_STATUS_SQL_TEMPLATE.format(debt_types=debt_types),
        })
