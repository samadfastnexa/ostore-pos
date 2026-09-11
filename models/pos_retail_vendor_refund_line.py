from odoo import fields, models, tools


class PosRetailVendorRefundLine(models.Model):
    """Every product sent back to a supplier, one row per item.

    We bought from a vendor, sent something back, and the vendor owes us a
    refund or a credit. That is the only thing this report is about.
    Customer refunds are the opposite flow and live in their own report
    (pos.retail.customer.refund.line), and nothing here ever mixes the two.

    A read-only view over native records, not a parallel store. Goods still go
    back through Odoo's own Return on a receipt, and the credit is still a
    native vendor credit note; stock valuation and the books are untouched.

    Two sources, because a vendor return is genuinely two events that do not
    always happen together:

      * The goods leaving: stock moves that return a receipt to a supplier
        location. This is where quantity, cost and the reason live.
      * The money coming back: vendor credit notes (in_refund). This is where
        the credit amount and whether it has been settled live.

    A supplier often credits later than the goods go back, or credits without
    a physical return at all -- a price correction, a short delivery. Forcing
    each into a single row would either hide the credits with no goods or
    invent goods for them. So both appear, and the Refunded Through column
    says which one a row is.
    """
    _name = 'pos.retail.vendor.refund.line'
    _description = "Vendor Refund Line"
    _auto = False
    _order = 'date desc, id desc'
    _rec_name = 'product_id'

    source = fields.Selection(
        [('return', "Goods returned"), ('credit_note', "Vendor credit note")],
        string="Recorded As", readonly=True)
    date = fields.Datetime(string="Return Date", readonly=True)
    company_id = fields.Many2one('res.company', string="Branch", readonly=True)
    partner_id = fields.Many2one('res.partner', string="Vendor", readonly=True)

    picking_id = fields.Many2one('stock.picking', string="Return Transfer", readonly=True)
    move_id = fields.Many2one('account.move', string="Credit Note", readonly=True)
    purchase_order_id = fields.Many2one('purchase.order', string="Purchase Order", readonly=True)
    original_picking_id = fields.Many2one(
        'stock.picking', string="Original Receipt", readonly=True,
        help="The delivery from the vendor that these goods came in on.")
    original_move_id = fields.Many2one(
        'account.move', string="Original Bill", readonly=True,
        help="The vendor bill this credit note reverses.")
    original_reference = fields.Char(
        string="Original Purchase / Receipt", readonly=True,
        help="The purchase order, receipt or bill being returned against.")

    product_id = fields.Many2one('product.product', string="Product", readonly=True)
    categ_id = fields.Many2one('product.category', string="Product Category", readonly=True)
    quantity = fields.Float(string="Returned Quantity", readonly=True, digits='Product Unit')
    unit_cost = fields.Monetary(string="Unit Cost", readonly=True, currency_field='currency_id')
    purchase_cost = fields.Monetary(
        string="Purchase Cost", readonly=True, currency_field='currency_id',
        help="What the returned goods cost when bought: quantity times the "
             "price on the purchase order.")
    credit_amount = fields.Monetary(
        string="Credit Amount", readonly=True, currency_field='currency_id',
        help="What the vendor credited, from the vendor credit note.")
    currency_id = fields.Many2one('res.currency', readonly=True)

    return_reason_id = fields.Many2one(
        'pos.retail.vendor.return.reason', string="Return Reason", readonly=True)
    reason_note = fields.Char(
        string="Reason (credit note)", readonly=True,
        help="A credit note records its reason as free text on the reversal, "
             "so it is shown as written.")
    user_id = fields.Many2one('res.users', string="Staff Member", readonly=True)
    status = fields.Selection(
        [('draft', "Draft"), ('pending', "Pending"), ('returned', "Goods Returned"),
         ('credit_pending', "Credit Not Yet Received"), ('credited', "Credited"),
         ('cancelled', "Cancelled")],
        string="Credit / Refund Status", readonly=True)

    def init(self):
        tools.drop_view_if_exists(self.env.cr, self._table)
        # Parity keeps ids unique across the two sources, as in the customer
        # view: returned-goods rows even, credit-note rows odd.
        self.env.cr.execute("""
            CREATE OR REPLACE VIEW %s AS (
                SELECT
                    sm.id * 2                              AS id,
                    'return'                               AS source,
                    sm.date                                AS date,
                    sm.company_id                          AS company_id,
                    COALESCE(sp.partner_id, po.partner_id) AS partner_id,
                    sp.id                                  AS picking_id,
                    NULL::integer                          AS move_id,
                    po.id                                  AS purchase_order_id,
                    osp.id                                 AS original_picking_id,
                    NULL::integer                          AS original_move_id,
                    COALESCE(po.name, osp.name)            AS original_reference,
                    sm.product_id                          AS product_id,
                    pt.categ_id                            AS categ_id,
                    CASE WHEN sm.state = 'done' THEN sm.quantity
                         ELSE sm.product_uom_qty END       AS quantity,
                    COALESCE(pol.price_unit, sm.price_unit) AS unit_cost,
                    (CASE WHEN sm.state = 'done' THEN sm.quantity
                          ELSE sm.product_uom_qty END)
                        * COALESCE(pol.price_unit, sm.price_unit, 0) AS purchase_cost,
                    NULL::numeric                          AS credit_amount,
                    COALESCE(po.currency_id, c.currency_id) AS currency_id,
                    sp.pos_retail_vendor_return_reason_id  AS return_reason_id,
                    NULL::varchar                          AS reason_note,
                    COALESCE(sp.user_id, sm.create_uid)    AS user_id,
                    CASE sm.state
                        WHEN 'done'   THEN 'returned'
                        WHEN 'cancel' THEN 'cancelled'
                        WHEN 'draft'  THEN 'draft'
                        ELSE 'pending'
                    END                                    AS status
                FROM stock_move sm
                JOIN stock_location dl       ON dl.id = sm.location_dest_id
                JOIN res_company c           ON c.id = sm.company_id
                JOIN product_product pp      ON pp.id = sm.product_id
                JOIN product_template pt     ON pt.id = pp.product_tmpl_id
                LEFT JOIN stock_picking sp   ON sp.id = sm.picking_id
                LEFT JOIN stock_move om      ON om.id = sm.origin_returned_move_id
                LEFT JOIN stock_picking osp  ON osp.id = om.picking_id
                LEFT JOIN purchase_order_line pol
                       ON pol.id = COALESCE(sm.purchase_line_id, om.purchase_line_id)
                LEFT JOIN purchase_order po  ON po.id = pol.order_id
                WHERE sm.origin_returned_move_id IS NOT NULL
                  AND dl.usage = 'supplier'

                UNION ALL

                SELECT
                    ml.id * 2 + 1                          AS id,
                    'credit_note'                          AS source,
                    m.invoice_date::timestamp              AS date,
                    m.company_id                           AS company_id,
                    m.partner_id                           AS partner_id,
                    NULL::integer                          AS picking_id,
                    m.id                                   AS move_id,
                    NULL::integer                          AS purchase_order_id,
                    NULL::integer                          AS original_picking_id,
                    m.reversed_entry_id                    AS original_move_id,
                    COALESCE(rm.name, m.invoice_origin)    AS original_reference,
                    ml.product_id                          AS product_id,
                    pt.categ_id                            AS categ_id,
                    ml.quantity                            AS quantity,
                    ml.price_unit                          AS unit_cost,
                    NULL::numeric                          AS purchase_cost,
                    ml.price_total                         AS credit_amount,
                    m.currency_id                          AS currency_id,
                    NULL::integer                          AS return_reason_id,
                    m.ref                                  AS reason_note,
                    COALESCE(m.invoice_user_id, m.create_uid) AS user_id,
                    CASE
                        WHEN m.state = 'draft'  THEN 'draft'
                        WHEN m.state = 'cancel' THEN 'cancelled'
                        WHEN m.payment_state IN ('paid', 'in_payment', 'reversed') THEN 'credited'
                        ELSE 'credit_pending'
                    END                                    AS status
                FROM account_move_line ml
                JOIN account_move m           ON m.id = ml.move_id
                LEFT JOIN account_move rm     ON rm.id = m.reversed_entry_id
                LEFT JOIN product_product pp  ON pp.id = ml.product_id
                LEFT JOIN product_template pt ON pt.id = pp.product_tmpl_id
                WHERE m.move_type = 'in_refund'
                  AND ml.display_type = 'product'
            )
        """ % self._table)
