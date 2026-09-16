import hashlib
import hmac
from dateutil.relativedelta import relativedelta

from odoo import _, api, fields, models
from odoo.exceptions import ValidationError
from odoo.tools import float_compare


class PosOrder(models.Model):
    _inherit = 'pos.order'

    discount_manager_id = fields.Many2one(
        'hr.employee', string="Approving Manager",
        help="Set when an order discount exceeded the cashier's limit and a "
             "manager authenticated via PIN to approve it.",
    )
    discount_reason_id = fields.Many2one(
        'pos.retail.discount.reason', string="Discount Reason",
        help="Why money was taken off this sale, picked by the cashier from the "
             "list your shop keeps. Recorded at the moment of sale so discounts "
             "can be reviewed later.",
    )
    discount_reason_notes = fields.Text(
        string="Discount Reason Notes",
        help="Anything the cashier typed to explain the discount beyond the "
             "reason chosen, e.g. the name of the regular customer it was given "
             "to.",
    )
    discount_input_type = fields.Selection(
        [('fixed', 'Fixed Amount'), ('percent', 'Percentage')],
        string="Discount Entry Type",
        help="Whether the cashier keyed the discount as a flat amount off or as "
             "a percentage. Kept for the record, since either way of entering it "
             "can end up as the same money off.",
    )
    # Credit-limit override: who let this customer go further into debt than
    # their limit allowed, and by how much. Recorded so the decision has a name
    # against it, the same way discount approvals do.
    pos_retail_credit_manager_id = fields.Many2one(
        'hr.employee', string="Credit Approved By",
        help="Set when a sale on Customer Credit would have taken the customer "
             "past their credit limit and a manager approved it by PIN.",
    )
    pos_retail_credit_over_amount = fields.Monetary(
        string="Amount Over Credit Limit", currency_field='currency_id',
        help="How far past their credit limit this sale pushed the customer, "
             "worked out at the moment it was approved. Zero means the sale "
             "stayed inside the limit.",
    )
    pos_retail_credit_before = fields.Monetary(
        string="Outstanding Before Sale", currency_field='currency_id',
        help="What the customer owed when the sale was approved. Stored rather "
             "than recomputed: their balance keeps moving, and an audit has to "
             "show the figure the manager actually saw.",
    )
    pos_retail_credit_after = fields.Monetary(
        string="Outstanding After Sale", currency_field='currency_id',
        help="What the customer owed once this sale was added on, captured at "
             "the moment of sale. Payments and purchases made afterwards do not "
             "change this figure.",
    )
    pos_retail_credit_limit = fields.Monetary(
        string="Credit Limit at Sale", currency_field='currency_id',
        help="The credit limit that applied when this sale was approved. Stored "
             "because limits get raised and lowered over time, and an audit has "
             "to show the limit in force on the day.",
    )

    pos_retail_on_account = fields.Monetary(
        string="Unpaid (Khata)", currency_field='currency_id',
        compute='_compute_pos_retail_on_account', store=True,
        help="How much of this sale the customer still owes: the part put on "
             "their khata instead of paid at the till. Zero means it was "
             "paid in full.",
    )

    # Depends on journal_id, not on payment_method_id.type: `type` is itself
    # computed and not stored, so it cannot appear in a stored field's
    # dependency chain. It derives from the journal (pos_payment_method.py's
    # _compute_type -- no cash/bank journal means pay_later), so following the
    # journal keeps a stored value correct if a payment method is ever
    # reconfigured, which naming `type` here would not.
    @api.depends('payment_ids.amount', 'payment_ids.payment_method_id',
                 'payment_ids.payment_method_id.journal_id')
    def _compute_pos_retail_on_account(self):
        """What the customer still owes on this sale.

        Exists because the order's own Status does not answer the question a
        shop actually asks. A sale settled entirely on the khata still reads
        "Paid", then "Posted" once the session closes -- correctly, because
        those describe the ORDER's life, not whether money came in. Read as
        plain English at a glance they say the opposite of the truth, and that
        misreading is worth money.

        The receivable was right all along (partner.credit matched the khata
        exactly on the live database). Only the reading was wrong, so this
        surfaces the figure rather than changing any behaviour.
        """
        for order in self:
            order.pos_retail_on_account = sum(
                payment.amount for payment in order.payment_ids
                if payment.payment_method_id.type == 'pay_later' or
                   any(k in (payment.payment_method_id.name or '').lower() for k in ('credit', 'khata', 'pay later', 'pay_later', 'udhar', 'customer account', 'on account'))
            )

    return_reason_id = fields.Many2one(
        'pos.retail.return.reason', string="Return Reason",
        help="Why the goods came back, picked by the cashier from the list your "
             "shop keeps. Only filled in on refunds.",
    )
    return_reason_notes = fields.Text(
        string="Return Reason Notes",
        help="Anything the cashier typed about the return beyond the reason "
             "chosen, e.g. what was wrong with the item.",
    )
    pos_retail_return_unlinked = fields.Boolean(
        string="Return Not Linked to Original Order", default=False,
        help="Set on a fast physical return where the cashier did not look up "
             "the original sale. The refund price is then the product's own "
             "current price rather than what was actually charged at the time, "
             "so this stays true on the record rather than the gap being "
             "silently invisible in reports.",
    )
    pos_retail_return_manager_id = fields.Many2one(
        'hr.employee', string="Return Approved By",
        help="The manager whose PIN cleared this return, when the register is "
             "set to require one. A named field of its own rather than reusing "
             "discount_manager_id: that one says who approved a price cut, and "
             "labelling a return with it would say the wrong thing on the "
             "receipt.",
    )

    # --- Fast physical returns -----------------------------------------------

    @api.model
    def pos_retail_find_return_source(self, reference, product_id, config_id=False):
        """Look up an order by its receipt number, for the OPTIONAL "link to
        original order" step on a fast return.

        Deliberately narrow: only ever called with a product already chosen,
        and only ever used to prefill that product's ORIGINAL price on THIS
        order -- never to browse someone's purchase history from a bare
        reference number. A cashier typing a wrong or partial reference gets a
        plain "not found", never someone else's order.

        `returnable_qty` is the ORIGINAL quantity minus whatever has already
        come back against this exact line, via refund_orderline_ids -- the
        same reverse link core's own with-receipt refund screen already uses
        to cap a return, read here rather than reinvented. A sale of 25 with
        5 already returned reports 20 returnable, not 25, so a second fast
        return months later cannot double up on the first one just because it
        went through a different screen.
        """
        reference = (reference or '').strip()
        if not reference:
            return {'found': False}

        order = self.sudo().search([
            ('company_id', 'in', self.env.companies.ids),
            '|', ('pos_reference', 'like', reference), ('name', '=', reference),
        ], limit=1, order='date_order desc')
        if not order:
            return {'found': False, 'reason': 'no_order'}

        config = self.env['pos.config'].browse(int(config_id or 0)).exists()
        if config and config.company_id not in self.env.companies:
            return {'found': False, 'reason': 'no_order'}
        if config and config.pos_retail_return_window_days and order.date_order:
            return_deadline = fields.Datetime.to_datetime(order.date_order).date() + \
                relativedelta(days=config.pos_retail_return_window_days)
            if fields.Date.context_today(self) > return_deadline:
                return {
                    'found': False,
                    'reason': 'outside_return_policy',
                    'order_name': order.pos_reference or order.name,
                    'return_deadline': fields.Date.to_string(return_deadline),
                }

        line = order.lines.filtered(
            lambda l: l.product_id.id == int(product_id) and l.qty > 0)[:1]
        if not line:
            return {
                'found': False, 'reason': 'no_matching_product',
                'order_name': order.pos_reference or order.name,
            }

        already_returned = sum(line.refund_orderline_ids.mapped(lambda l: abs(l.qty)))
        returnable = max(line.qty - already_returned, 0.0)

        return {
            'found': True,
            'order_id': order.id,
            'order_line_id': line.id,
            'order_name': order.pos_reference or order.name,
            'order_date': fields.Date.to_string(order.date_order) if order.date_order else False,
            'partner_id': order.partner_id.id,
            'partner_name': order.partner_id.name,
            'price_unit': line.price_unit,
            'original_qty': line.qty,
            'already_returned_qty': already_returned,
            'returnable_qty': returnable,
        }

    # --- Receipt management -------------------------------------------------

    def _pos_retail_receipt_data(self):
        """Everything the PDF receipt templates need, computed once here so the
        QWeb stays declarative.

        Order-level discounts are ordinary order lines carrying the config's
        discount product (that is how pos_discount records them), so they are
        separated out of the product lines rather than being a field on the
        order. Round-off comes from this addon's own discount log, which
        already snapshots it at sale time.
        """
        self.ensure_one()
        discount_product = self.config_id.discount_product_id
        order_discount_lines = self.lines.filtered(
            lambda l: discount_product and l.product_id == discount_product)
        product_lines = self.lines - order_discount_lines

        product_discount = sum(
            (l.qty * l.price_unit) * (l.discount or 0.0) / 100.0 for l in product_lines)
        order_discount = abs(sum(order_discount_lines.mapped('price_subtotal_incl')))

        log = self.env['pos.retail.discount.log'].sudo().search(
            [('order_id', '=', self.id)], limit=1)

        # Tax lines grouped by the tax names applied, so a receipt can show
        # "GST 17%: 340.00" rather than one opaque total.
        tax_groups = {}
        for line in product_lines:
            if not line.tax_ids:
                continue
            key = ", ".join(line.tax_ids.mapped('name'))
            tax_groups.setdefault(key, 0.0)
            tax_groups[key] += line.price_subtotal_incl - line.price_subtotal
        if not tax_groups and self.amount_tax:
            tax_groups[_("Tax")] = self.amount_tax

        payments = []
        for payment in self.payment_ids.filtered(lambda p: not p.is_change):
            payments.append({
                'name': payment.payment_method_id.name,
                'amount': payment.amount,
                'date': payment.payment_date,
                'ref': payment.transaction_id or payment.payment_ref_no or (
                    "****%s" % payment.card_no if payment.card_no else ''),
            })

        return {
            'product_lines': product_lines,
            'subtotal': sum(product_lines.mapped('price_subtotal_incl')) + product_discount,
            'product_discount': product_discount,
            'order_discount': order_discount,
            'round_off': log.round_off_amount if log else 0.0,
            'tax_groups': tax_groups,
            'payments': payments,
            'grand_total': self.amount_total,
            'paid': self.amount_paid,
            'change': self.amount_return,
            'credit_return_info': self._pos_retail_credit_return_info() if self.is_refund else False,
        }

    def _pos_retail_credit_return_info(self):
        """The extra section a return receipt carries that an ordinary sale
        does not: what this undoes, how the money actually went back, who
        cleared it, and -- only when it genuinely touched the customer's
        account -- what that account stood at before and after.

        The balance figures are an ESTIMATE, said as one on the receipt
        itself rather than dressed up as posted fact. A POS credit only
        reaches the customer's real receivable when the till session closes
        (see pos.session._create_pay_later_receivable_lines); this receipt
        prints the moment the sale is rung up, which is always earlier than
        that. So "before" is the customer's current, already-posted balance,
        and "after" is that figure minus this return -- correct once the day
        closes, and told as a running total rather than a closed book before
        then.
        """
        self.ensure_one()
        original_orders = self.lines.refunded_orderline_id.order_id
        credit_payment = self.payment_ids.filtered(
            lambda p: p.payment_method_id.type == 'pay_later')[:1]

        info = {
            'original_orders': [
                {'reference': o.pos_reference or o.name,
                 'date': o.date_order}
                for o in original_orders
            ],
            'unlinked': self.pos_retail_return_unlinked,
            'authorized_by': self.pos_retail_return_manager_id.name or False,
            'refund_amount': abs(self.amount_total),
        }

        if credit_payment:
            partner = self.partner_id
            if partner:
                # sudo: a cashier printing a receipt has no reason to hold
                # accounting rights, and the figure itself is already shown
                # to them on the payment screen before they get here.
                balance_before = partner.sudo().pos_outstanding_balance
                info['balance_before'] = balance_before
                info['balance_after'] = balance_before - info['refund_amount']
                info['balance_is_estimate'] = True
                if balance_before > 0:
                    info['disposition'] = _("Adjusted against Outstanding Balance")
                else:
                    info['disposition'] = _("Added as Credit")
            else:
                info['disposition'] = _("Added as Credit (%s)", credit_payment.payment_method_id.name)
        else:
            cash_payment = self.payment_ids.filtered(lambda p: p.payment_method_id.is_cash_count)[:1]
            if cash_payment and len(self.payment_ids) == 1:
                info['disposition'] = _("Refunded in Cash")
            else:
                methods = self.payment_ids.mapped('payment_method_id.name')
                if methods:
                    info['disposition'] = _("Refunded through Payment Method (%s)") % ", ".join(methods)
                else:
                    info['disposition'] = _("Not yet paid")

        return info

    def action_print_receipt_thermal(self):
        return self.env.ref(
            'pos_retail.action_report_pos_receipt_thermal').report_action(self, config=False)

    def action_print_receipt_a4(self):
        return self.env.ref(
            'pos_retail.action_report_pos_receipt_a4').report_action(self, config=False)

    def get_public_receipt_token(self):
        self.ensure_one()
        secret = self.env['ir.config_parameter'].sudo().get_param('database.secret', 'pos_retail_khata')
        msg = f'pos_receipt_{self.id}'.encode('utf-8')
        return hmac.new(secret.encode('utf-8'), msg, hashlib.sha256).hexdigest()[:16]

    def get_public_pdf_url(self):
        self.ensure_one()
        base_url = self.get_base_url().rstrip('/')
        if self.access_token:
            return f"{base_url}/pos_retail/portal/receipt/pdf/{self.access_token}"
        token = self.get_public_receipt_token()
        return f"{base_url}/pos_retail/portal/receipt/pdf/{self.id}?token={token}"

    @api.model
    def get_receipt_share_payload(self, order_id_or_access_token):
        """Return public URL and share details for a POS order or refund."""
        domain = [('access_token', '=', order_id_or_access_token)] if isinstance(order_id_or_access_token, str) and not order_id_or_access_token.isdigit() else [('id', '=', int(order_id_or_access_token))]
        order = self.sudo().search(domain, limit=1)
        if not order:
            return {}
        return {
            'order_id': order.id,
            'access_token': order.access_token,
            'public_url': order.get_public_pdf_url(),
            'name': order.pos_reference or order.name,
        }

    def action_email_receipt_pdf(self):
        """Open the mail composer pre-loaded with the receipt template; the A4
        PDF rides along as an attachment (mail.template.report_template_ids).
        """
        self.ensure_one()
        template = self.env.ref('pos_retail.mail_template_pos_receipt_pdf', raise_if_not_found=False)
        return {
            'type': 'ir.actions.act_window',
            'name': _("Email Receipt"),
            'res_model': 'mail.compose.message',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_model': 'pos.order',
                'default_res_ids': self.ids,
                'default_template_id': template.id if template else False,
                'default_composition_mode': 'comment',
                'default_partner_ids': self.partner_id.ids,
            },
        }

    @api.model
    def _load_pos_data_fields(self, config):
        result = super()._load_pos_data_fields(config)
        # An empty list means "load every field" (pos.load.mixin default, which
        # core pos.order relies on) — appending names to it would narrow the
        # schema to only those fields and break the whole POS (no lines, no
        # totals). Only append when a base module has set an explicit list.
        if not result:
            return result
        for field in ('discount_manager_id', 'discount_reason_id', 'discount_reason_notes', 'discount_input_type',
                      'return_reason_id', 'return_reason_notes',
                      'pos_retail_return_unlinked', 'pos_retail_return_manager_id',
                      'pos_retail_credit_manager_id', 'pos_retail_credit_over_amount',
                      'pos_retail_credit_before', 'pos_retail_credit_after',
                      'pos_retail_credit_limit'):
            if field not in result:
                result.append(field)
        return result

    def _force_create_picking_real_time(self):
        """Always force real-time picking creation per order.

        Ensures stock pickings are created and validated immediately upon
        order payment in real time, decrements stock on hand in Postgres,
        and ensures session closing automatically skips double-deductions.
        """
        return True

    def _should_create_picking_real_time(self):
        return True

    def _process_saved_order(self, draft):
        # Snapshot stock BEFORE calling super() (which is where the picking
        # actually gets created+validated, decrementing stock) so we capture
        # a genuine "before" reading, then let the arithmetic (previous - qty)
        # derive "after" rather than re-reading live (which could pick up
        # other concurrent orders' effects under multi-terminal load).
        movement_lines = self.env['pos.order.line']
        stock_before = {}
        will_create_picking = (
            not draft and self.state != 'cancel'
            and not self.picking_ids and not self.shipping_date
            and self._should_create_picking_real_time()
        )
        if will_create_picking:
            movement_lines = self.lines.filtered(
                lambda l: l.product_id.type == 'consu' and l.product_id.is_storable and l.qty
            )
            for product in movement_lines.product_id:
                stock_before[product.id] = product.qty_available

        result = super()._process_saved_order(draft)

        if movement_lines:
            self.env['pos.retail.inventory.movement'].sudo()._create_from_order_lines(
                movement_lines, stock_before
            )

        if not draft and self.state != 'cancel':
            self.env['pos.retail.discount.log'].sudo()._create_from_order(self)
            self.env['pos.retail.line.discount.log'].sudo()._create_from_order(self)

        return result


class PosOrderLine(models.Model):
    _inherit = 'pos.order.line'

    pos_retail_is_roundoff = fields.Boolean(
        string="Round-Off Line", readonly=True, copy=False,
        help="Marks the line that rounds an order to a whole cash figure. Kept "
             "as a flag rather than guessed from the product, because the same "
             "discount product also carries ordinary order discounts -- without "
             "it, rounding a second time would stack lines instead of replacing "
             "the first.",
    )

    # Which package was sold, when the line came from scanning a package
    # barcode. The quantity on the line stays in the product's own unit (so
    # stock moves correctly), and this records the size the customer actually
    # bought, for the receipt and for the package reports.
    pos_retail_package_id = fields.Many2one(
        'product.uom', string="Package", ondelete='set null', index='btree_not_null',
        help="The pack size the customer actually bought on this line, e.g. a "
             "5 kg bag, filled in when a package barcode was scanned. Blank "
             "means the item was sold loose in its own unit.",
    )

    # Snapshots of the product's selling range as it stood when the sale was
    # rung up. The product's own prices drift over time, so reporting "sold
    # below default" months later has to compare against what was in force then.
    pos_retail_default_price = fields.Monetary(
        string="Default Price", currency_field='currency_id',
        help="The product's standard selling price at the moment of sale.",
    )
    pos_retail_min_price = fields.Monetary(
        string="Minimum Allowed Price", currency_field='currency_id',
        help="The lowest price this item could be sold at without a manager, as "
             "the rule stood when this line was rung up. Changing the product's "
             "limits later does not change this.",
    )
    pos_retail_max_price = fields.Monetary(
        string="Maximum Allowed Price", currency_field='currency_id',
        help="The highest price this item could be sold at without a manager, "
             "as the rule stood when this line was rung up. Changing the "
             "product's limits later does not change this.",
    )
    pos_retail_price_state = fields.Selection(
        [
            ('default', "Default Price"),
            ('adjusted', "Adjusted (within range)"),
            ('overridden', "Overridden (outside range)"),
        ],
        string="Price Status", default='default', index=True,
        help="How the price charged compared with the rules at the time: the "
             "standard price, changed but still inside the allowed range, or "
             "pushed outside it, which needs a manager's approval.",
    )
    pos_retail_price_manager_id = fields.Many2one(
        'hr.employee', string="Price Approved By",
        help="Set when the price fell outside the allowed range and a manager "
             "authenticated via PIN to approve it.",
    )
    pos_retail_price_reason_id = fields.Many2one(
        'pos.retail.price.reason', string="Price Reason",
        help="Why the price on this line was changed, picked by the cashier "
             "from the list your shop keeps. Recorded at the moment of sale.",
    )
    pos_retail_price_variance = fields.Monetary(
        string="Price Variance", currency_field='currency_id',
        compute='_compute_pos_retail_price_variance', store=True,
        help="Difference between the price actually charged and the product's "
             "default selling price at the time of sale. Negative means sold "
             "below the default.",
    )

    @api.depends('price_unit', 'pos_retail_default_price')
    def _compute_pos_retail_price_variance(self):
        # Stored so the report can filter on it: an Odoo domain cannot compare
        # two fields to each other, so "sold below default" needs a real column.
        for line in self:
            if line.pos_retail_default_price:
                line.pos_retail_price_variance = line.price_unit - line.pos_retail_default_price
            else:
                line.pos_retail_price_variance = 0.0

    @api.model
    def _load_pos_data_fields(self, config):
        result = super()._load_pos_data_fields(config)
        # Same guard as pos.order above: an empty list means "load every field",
        # so appending to it would narrow the schema and break the POS.
        if not result:
            return result
        for field in ('pos_retail_default_price', 'pos_retail_min_price', 'pos_retail_max_price',
                      'pos_retail_price_state', 'pos_retail_price_manager_id',
                      'pos_retail_price_reason_id', 'pos_retail_package_id',
                      'pos_retail_is_roundoff', 'pos_retail_returned_qty',
                      'pos_retail_returnable_qty',
                      'pos_retail_line_discount_manager_id',
                      'pos_retail_line_discount_input_type',
                      'pos_retail_line_discount_reason',
                      'pos_retail_product_condition',
                      'pos_retail_return_pricing_policy'):
            if field not in result:
                result.append(field)
        return result

    pos_retail_returned_qty = fields.Float(
        string="Already Returned Qty",
        compute='_compute_pos_retail_return_quantities',
        help="Total quantity already returned against this sale line across all refund transactions.",
    )
    pos_retail_returnable_qty = fields.Float(
        string="Returnable Qty",
        compute='_compute_pos_retail_return_quantities',
        help="Maximum quantity that can still be returned (Original Quantity - Previously Returned Quantity).",
    )

    pos_retail_product_condition = fields.Selection(
        [
            ('resalable', "Resalable / Good"),
            ('damaged', "Damaged"),
            ('defective', "Defective / Faulty"),
            ('used', "Used / Opened"),
            ('packaging_missing', "Packaging Missing"),
            ('other', "Other"),
        ],
        string="Product Condition",
        default='resalable',
        help="Physical condition of the returned item.",
    )
    pos_retail_return_pricing_policy = fields.Selection(
        [
            ('current_price', "Current Selling Price"),
            ('lowest_price', "Lowest Selling Price in Period"),
            ('cost', "Product Cost"),
            ('manager_price', "Manager Determines Price"),
        ],
        string="Return Pricing Policy",
        help="Pricing policy used when this item was refunded.",
    )

    # ── Per-line discount fields ─────────────────────────────────────────────
    pos_retail_line_discount_manager_id = fields.Many2one(
        'hr.employee',
        string="Line Discount Approved By",
        help="Set when the cashier applied a discount that pushed the final price "
             "below the product's minimum_selling_price and a manager approved it "
             "by PIN. Blank means no approval was required (either the discount "
             "stayed above the minimum or the product has no minimum).",
    )
    pos_retail_line_discount_input_type = fields.Selection(
        [('percent', "Percentage"), ('fixed', "Fixed Amount")],
        string="Line Discount Entry Type",
        help="Whether the cashier keyed the line discount as a percentage or a "
             "flat amount off. Both compile to the same core discount% field; "
             "this records how it was entered for the audit log.",
    )
    pos_retail_line_discount_reason = fields.Char(
        string="Line Discount Reason",
        help="Free-text note the cashier entered when applying a line discount.",
    )

    @api.depends('qty', 'refund_orderline_ids.qty', 'refund_orderline_ids.order_id.state')
    def _compute_pos_retail_return_quantities(self):
        for line in self:
            if line.qty > 0:
                refunds = line.refund_orderline_ids.filtered(lambda l: l.order_id.state != 'cancel')
                returned = abs(sum(refunds.mapped('qty')))
                line.pos_retail_returned_qty = returned
                line.pos_retail_returnable_qty = max(0.0, line.qty - returned)
            else:
                line.pos_retail_returned_qty = 0.0
                line.pos_retail_returnable_qty = 0.0

    @api.constrains('qty', 'refunded_orderline_id')
    def _check_pos_retail_return_quantity(self):
        """Enforce: Original Quantity - Previously Returned Quantity = Returnable Quantity.
        A user must never be able to return more than the remaining returnable quantity.
        """
        precision = self.env['decimal.precision'].precision_get('Product Unit of Measure')
        for line in self:
            if line.qty < 0 and line.refunded_orderline_id:
                orig = line.refunded_orderline_id
                other_refunds = orig.refund_orderline_ids.filtered(
                    lambda l: l.id != line.id and l.order_id.state != 'cancel'
                )
                already_returned = abs(sum(other_refunds.mapped('qty')))
                returnable = max(0.0, orig.qty - already_returned)
                return_qty = abs(line.qty)
                if float_compare(return_qty, returnable, precision_digits=precision) > 0:
                    raise ValidationError(_(
                        "Cannot return %(return_qty)s units of \"%(product)s\". "
                        "Only %(returnable)s units remaining to return (Original: %(orig)s, Already returned: %(returned)s).",
                        product=line.product_id.display_name,
                        return_qty=return_qty,
                        returnable=returnable,
                        orig=orig.qty,
                        returned=already_returned,
                    ))

    def _pos_retail_price_check_applies(self):
        """Only ordinary positive-quantity sale lines are range-checked.

        Refund lines carry a negative quantity and are priced from the original
        order, the order-level discount line is a synthetic negative line on the
        config's discount product, and free lines have nothing to validate.
        """
        self.ensure_one()
        if self.qty <= 0 or self.price_unit <= 0:
            return False
        discount_product = self.order_id.config_id.discount_product_id
        if discount_product and self.product_id.id == discount_product.id:
            return False
        return True

    @api.constrains('price_unit', 'pos_retail_min_price', 'pos_retail_max_price',
                    'pos_retail_price_manager_id')
    def _check_price_within_allowed_range(self):
        """Enforce the selling range server-side.

        The POS gate for price control (cashierHasPriceControlRights) is UI-only
        -- nothing in core validates the posted price -- so a tampered client
        could push any amount. A price outside the range is only accepted when a
        manager actually approved it.
        """
        precision = self.env['decimal.precision'].precision_get('Product Price')
        for line in self:
            if line.pos_retail_price_manager_id or not line._pos_retail_price_check_applies():
                continue
            minimum = line.pos_retail_min_price
            maximum = line.pos_retail_max_price
            if minimum and float_compare(line.price_unit, minimum, precision_digits=precision) < 0:
                raise ValidationError(_(
                    "The price %(price).2f for \"%(product)s\" is below the minimum "
                    "selling price of %(minimum).2f. A manager must approve it.",
                    price=line.price_unit, product=line.product_id.display_name,
                    minimum=minimum,
                ))
            if maximum and float_compare(line.price_unit, maximum, precision_digits=precision) > 0:
                raise ValidationError(_(
                    "The price %(price).2f for \"%(product)s\" exceeds the maximum "
                    "selling price of %(maximum).2f. A manager must approve it.",
                    price=line.price_unit, product=line.product_id.display_name,
                    maximum=maximum,
                ))

    @api.constrains('discount', 'price_unit', 'pos_retail_line_discount_manager_id')
    def _check_pos_retail_line_discount(self):
        """Enforce minimum selling price against line-level discounts server-side.

        A cashier who manipulates the browser payload or calls the JSON-RPC
        endpoint directly could send a discount that pushes the final price
        below minimum_selling_price without the manager approval the UI
        enforces.  This constraint is the backend backstop.

        The check intentionally skips:
          * Refund/negative-qty lines (their price derives from the original).
          * Lines with no discount (nothing to validate).
          * Lines where a manager already approved (pos_retail_line_discount_manager_id set).
          * Synthetic order-level discount lines on config.discount_product_id.
          * Products with minimum_selling_price = 0 (not configured).
        """
        precision = self.env['decimal.precision'].precision_get('Product Price')
        for line in self:
            if line.pos_retail_line_discount_manager_id:
                continue
            if not line.discount or not line._pos_retail_price_check_applies():
                continue
            min_price = line.product_id.product_tmpl_id.minimum_selling_price
            if not min_price:
                continue
            final_price = line.price_unit * (1.0 - line.discount / 100.0)
            if float_compare(final_price, min_price, precision_digits=precision) < 0:
                raise ValidationError(_(
                    "Product \"%(product)s\": the %(discount).2f%% discount brings "
                    "the final price to %(final).2f, which is below the minimum "
                    "selling price of %(minimum).2f. "
                    "A manager must approve this discount.",
                    product=line.product_id.display_name,
                    discount=line.discount,
                    final=final_price,
                    minimum=min_price,
                ))
