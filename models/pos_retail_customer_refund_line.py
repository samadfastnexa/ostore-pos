from odoo import fields, models, tools


class PosRetailCustomerRefundLine(models.Model):
    """Every product a customer brought back, one row per item.

    A customer bought from us, returned something, and we refunded or
    credited them. That is the only thing this report is about. Money going
    back to a customer and money coming back from a supplier are opposite
    flows with different owners, so vendor returns live in a separate report
    (pos.retail.vendor.refund.line) with its own menu, permission and KPIs,
    and nothing here ever mixes the two.

    A read-only view over native records, not a parallel store. Refunds are
    still made the ordinary way -- a refund at the till, or a credit note
    against a customer invoice -- and stock and accounting are handled by
    Odoo exactly as before. This only gathers them into one place the shop
    can read.

    Two sources:

      * POS refund lines. The negative-quantity lines of a refund order,
        with the reason the cashier picked and the original sale they undo.
      * Customer credit notes (out_refund) raised against an invoice.

    THE DOUBLE-COUNT, and why it is excluded rather than tolerated. An
    invoiced POS refund produces BOTH records: the refund order at the till
    and a credit note in accounting. Counting both would report every
    invoiced refund twice, and it would do it silently -- the totals would
    simply be wrong. So a credit note that belongs to a POS order is left
    out; the POS row already carries it, with the reason and cashier the
    credit note does not have.
    """
    _name = 'pos.retail.customer.refund.line'
    _description = "Customer Refund Line"
    _auto = False
    _order = 'date desc, id desc'
    _rec_name = 'product_id'

    source = fields.Selection(
        [('pos', "Till refund"), ('invoice', "Credit note")],
        string="Refunded Through", readonly=True)
    date = fields.Datetime(string="Refund Date", readonly=True)
    company_id = fields.Many2one('res.company', string="Branch", readonly=True)
    partner_id = fields.Many2one('res.partner', string="Customer", readonly=True)

    pos_order_id = fields.Many2one('pos.order', string="Refund Order", readonly=True)
    move_id = fields.Many2one('account.move', string="Credit Note", readonly=True)
    original_pos_order_id = fields.Many2one(
        'pos.order', string="Original Sale", readonly=True,
        help="The till sale this refund undoes.")
    original_move_id = fields.Many2one(
        'account.move', string="Original Invoice", readonly=True,
        help="The customer invoice this credit note reverses.")
    original_reference = fields.Char(
        string="Original Sale / Order", readonly=True,
        help="The sale or invoice being refunded, whichever this row came from.")

    product_id = fields.Many2one('product.product', string="Product", readonly=True)
    categ_id = fields.Many2one('product.category', string="Product Category", readonly=True)
    quantity = fields.Float(string="Quantity", readonly=True, digits='Product Unit')
    amount = fields.Monetary(string="Refund Amount", readonly=True, currency_field='currency_id')
    currency_id = fields.Many2one('res.currency', readonly=True)

    return_reason_id = fields.Many2one(
        'pos.retail.return.reason', string="Refund Reason", readonly=True)
    reason_note = fields.Char(
        string="Reason (credit note)", readonly=True,
        help="Credit notes record their reason as free text on the reversal "
             "rather than from the till's reason list, so it is shown here "
             "as written.")
    employee_id = fields.Many2one('hr.employee', string="Cashier", readonly=True)
    user_id = fields.Many2one('res.users', string="Staff Member", readonly=True)
    payment_method_id = fields.Many2one(
        'pos.payment.method', string="Refund Method", readonly=True,
        help="How the money went back to the customer. Where a refund was split "
             "across methods, the largest one is shown.")
    status = fields.Selection(
        [('draft', "Draft"), ('pending', "Awaiting Payment"),
         ('refunded', "Refunded"), ('cancelled', "Cancelled")],
        string="Refund Status", readonly=True)

    def init(self):
        tools.drop_view_if_exists(self.env.cr, self._table)
        # Ids are made unique across the two sources by parity: till lines are
        # even, credit-note lines odd. A plain UNION of two id columns would
        # collide, and the web client keys rows on id.
        self.env.cr.execute("""
            CREATE OR REPLACE VIEW %s AS (
                SELECT
                    l.id * 2                          AS id,
                    'pos'                             AS source,
                    o.date_order                      AS date,
                    o.company_id                      AS company_id,
                    o.partner_id                      AS partner_id,
                    o.id                              AS pos_order_id,
                    NULL::integer                     AS move_id,
                    ro.id                             AS original_pos_order_id,
                    NULL::integer                     AS original_move_id,
                    COALESCE(ro.pos_reference, ro.name) AS original_reference,
                    l.product_id                      AS product_id,
                    pt.categ_id                       AS categ_id,
                    -l.qty                            AS quantity,
                    -l.price_subtotal_incl            AS amount,
                    -- pos_order.currency_id is a related field with no column
                    -- of its own; it comes from the register, whose currency
                    -- IS stored, so read it from there.
                    pc.currency_id                    AS currency_id,
                    o.return_reason_id                AS return_reason_id,
                    NULL::varchar                     AS reason_note,
                    o.employee_id                     AS employee_id,
                    o.user_id                         AS user_id,
                    (SELECT p.payment_method_id
                       FROM pos_payment p
                      WHERE p.pos_order_id = o.id
                   ORDER BY abs(p.amount) DESC, p.id
                      LIMIT 1)                        AS payment_method_id,
                    CASE o.state
                        WHEN 'draft'  THEN 'draft'
                        WHEN 'cancel' THEN 'cancelled'
                        ELSE 'refunded'
                    END                               AS status
                FROM pos_order_line l
                JOIN pos_order o          ON o.id = l.order_id
                JOIN pos_session ps       ON ps.id = o.session_id
                JOIN pos_config pc        ON pc.id = ps.config_id
                JOIN product_product pp   ON pp.id = l.product_id
                JOIN product_template pt  ON pt.id = pp.product_tmpl_id
                LEFT JOIN pos_order_line rl ON rl.id = l.refunded_orderline_id
                LEFT JOIN pos_order ro      ON ro.id = rl.order_id
                WHERE o.is_refund = TRUE
                  AND l.qty < 0

                UNION ALL

                SELECT
                    ml.id * 2 + 1                     AS id,
                    'invoice'                         AS source,
                    m.invoice_date::timestamp         AS date,
                    m.company_id                      AS company_id,
                    m.partner_id                      AS partner_id,
                    NULL::integer                     AS pos_order_id,
                    m.id                              AS move_id,
                    NULL::integer                     AS original_pos_order_id,
                    m.reversed_entry_id               AS original_move_id,
                    rm.name                           AS original_reference,
                    ml.product_id                     AS product_id,
                    pt.categ_id                       AS categ_id,
                    ml.quantity                       AS quantity,
                    ml.price_total                    AS amount,
                    m.currency_id                     AS currency_id,
                    NULL::integer                     AS return_reason_id,
                    m.ref                             AS reason_note,
                    NULL::integer                     AS employee_id,
                    m.invoice_user_id                 AS user_id,
                    NULL::integer                     AS payment_method_id,
                    CASE
                        WHEN m.state = 'draft'  THEN 'draft'
                        WHEN m.state = 'cancel' THEN 'cancelled'
                        WHEN m.payment_state IN ('paid', 'in_payment', 'reversed') THEN 'refunded'
                        ELSE 'pending'
                    END                               AS status
                FROM account_move_line ml
                JOIN account_move m        ON m.id = ml.move_id
                LEFT JOIN account_move rm  ON rm.id = m.reversed_entry_id
                LEFT JOIN product_product pp  ON pp.id = ml.product_id
                LEFT JOIN product_template pt ON pt.id = pp.product_tmpl_id
                WHERE m.move_type = 'out_refund'
                  AND ml.display_type = 'product'
                  -- The till refund already carries this one; see the class
                  -- docstring for why counting both would be silently wrong.
                  AND NOT EXISTS (
                      SELECT 1 FROM pos_order po WHERE po.account_move = m.id
                  )
            )
        """ % self._table)
