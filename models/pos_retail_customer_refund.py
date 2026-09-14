# -*- coding: utf-8 -*-
import hashlib
import hmac
from urllib.parse import quote_plus

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError


def _get_customer_refund_token(env, refund_id):
    secret = env['ir.config_parameter'].sudo().get_param('database.secret', 'pos_retail_khata')
    msg = f'customer_refund_{refund_id}'.encode('utf-8')
    return hmac.new(secret.encode('utf-8'), msg, hashlib.sha256).hexdigest()[:16]


class PosRetailCustomerRefund(models.Model):
    _name = 'pos.retail.customer.refund'
    _description = "Customer Refund"
    _order = 'date desc, id desc'
    _inherit = ['mail.thread', 'mail.activity.mixin']

    name = fields.Char(
        string="Refund Number",
        required=True,
        copy=False,
        readonly=True,
        default='/',
        index=True,
    )
    partner_id = fields.Many2one(
        'res.partner',
        string="Customer",
        required=True,
        tracking=True,
        index=True,
    )
    partner_balance = fields.Monetary(
        string="Current Net Balance Owed",
        compute='_compute_partner_balance',
        currency_field='currency_id',
    )
    date = fields.Datetime(
        string="Refund Date",
        default=fields.Datetime.now,
        required=True,
        tracking=True,
    )
    company_id = fields.Many2one(
        'res.company',
        string="Branch / Company",
        required=True,
        default=lambda self: self.env.company,
        index=True,
    )
    currency_id = fields.Many2one(
        'res.currency',
        related='company_id.currency_id',
        readonly=True,
    )
    user_id = fields.Many2one(
        'res.users',
        string="Processed By",
        default=lambda self: self.env.user,
        required=True,
    )
    return_type = fields.Selection(
        [
            ('no_receipt', "No Receipt / Quick Return"),
            ('linked', "Receipt / Linked Return"),
        ],
        string="Return Mode",
        default='no_receipt',
        required=True,
    )
    original_pos_order_id = fields.Many2one(
        'pos.order',
        string="Original POS Order",
    )
    original_invoice_id = fields.Many2one(
        'account.move',
        string="Original Invoice",
    )
    original_reference = fields.Char(
        string="Original Reference / Receipt No.",
    )
    pricing_policy = fields.Selection(
        [
            ('current_price', "Current Selling Price"),
            ('lowest_price', "Lowest Selling Price in Period"),
            ('cost', "Product Cost"),
            ('manager_price', "Manager Determines Price"),
        ],
        string="Pricing Policy",
        default='current_price',
        required=True,
    )
    requires_manager_approval = fields.Boolean(
        string="Manager Approval Required",
        compute='_compute_manager_approval_needed',
        store=True,
    )
    manager_id = fields.Many2one(
        'hr.employee',
        string="Approved By Manager",
        tracking=True,
    )
    manager_notes = fields.Text(string="Manager Approval Notes")
    refund_method = fields.Selection(
        [
            ('cash', "Cash Refund"),
            ('payment_method', "Payment Method (Bank / Card)"),
            ('credit_ledger', "Credit to Customer Ledger"),
            ('adjust_outstanding', "Adjust Against Customer Outstanding Debt"),
        ],
        string="Settlement Option",
        default='cash',
        required=True,
        tracking=True,
    )
    journal_id = fields.Many2one(
        'account.journal',
        string="Payment Journal",
        domain="[('company_id', '=', company_id)]",
    )
    state = fields.Selection(
        [
            ('draft', "Draft"),
            ('confirmed', "Confirmed"),
            ('done', "Processed"),
            ('cancel', "Cancelled"),
        ],
        string="Status",
        default='draft',
        required=True,
        tracking=True,
        index=True,
    )
    line_ids = fields.One2many(
        'pos.retail.customer.refund.item',
        'refund_id',
        string="Refund Lines",
        copy=True,
    )
    amount_total = fields.Monetary(
        string="Total Refund Amount",
        compute='_compute_amounts',
        store=True,
        currency_field='currency_id',
        tracking=True,
    )
    previous_outstanding = fields.Monetary(
        string="Previous Outstanding Balance",
        currency_field='currency_id',
    )
    new_outstanding = fields.Monetary(
        string="New Outstanding Balance",
        compute='_compute_amounts',
        store=True,
        currency_field='currency_id',
    )
    picking_id = fields.Many2one(
        'stock.picking',
        string="Stock Return Transfer",
        readonly=True,
        copy=False,
    )
    credit_note_id = fields.Many2one(
        'account.move',
        string="Customer Credit Note",
        readonly=True,
        copy=False,
    )
    payment_id = fields.Many2one(
        'account.payment',
        string="Refund Payment",
        readonly=True,
        copy=False,
    )
    notes = fields.Text(string="Internal Notes")
    access_token = fields.Char(string="Access Token", copy=False)

    @api.depends('partner_id')
    def _compute_partner_balance(self):
        for rec in self:
            rec.partner_balance = rec.partner_id.pos_outstanding_balance if rec.partner_id else 0.0

    @api.depends('amount_total', 'pricing_policy', 'company_id')
    def _compute_manager_approval_needed(self):
        for rec in self:
            cfg = self.env['pos.config'].search([('company_id', '=', rec.company_id.id)], limit=1)
            approval_mode = cfg.pos_retail_no_receipt_approval_mode if cfg else 'amount'
            threshold = cfg.pos_retail_no_receipt_approval_limit if cfg else 3000.0
            if rec.pricing_policy == 'manager_price':
                rec.requires_manager_approval = True
            elif approval_mode == 'always':
                rec.requires_manager_approval = True
            elif approval_mode == 'amount' and rec.amount_total > threshold:
                rec.requires_manager_approval = True
            else:
                rec.requires_manager_approval = False

    @api.depends('line_ids.subtotal', 'refund_method', 'previous_outstanding', 'state')
    def _compute_amounts(self):
        for rec in self:
            total = sum(rec.line_ids.mapped('subtotal'))
            rec.amount_total = total
            if rec.refund_method in ('credit_ledger', 'adjust_outstanding'):
                rec.new_outstanding = rec.previous_outstanding - total
            else:
                rec.new_outstanding = rec.previous_outstanding

    def get_public_pdf_url(self):
        self.ensure_one()
        if not self.access_token:
            self.access_token = _get_customer_refund_token(self.env, self.id)
        base_url = self.env['ir.config_parameter'].sudo().get_param('web.base.url', '')
        return f"{base_url}/pos_retail/portal/customer_refund/pdf/{self.id}?token={self.access_token}"

    def action_confirm(self):
        self.ensure_one()
        if not self.line_ids:
            raise UserError(_("Please add at least one product line to refund."))
        for line in self.line_ids:
            if line.quantity <= 0:
                raise ValidationError(_("Return quantity must be greater than zero for %s.") % line.product_id.display_name)
            if line.return_reason_id.name and 'other' in line.return_reason_id.name.lower() and not line.reason_note:
                raise ValidationError(_("Please provide a note for the 'Other' return reason on line %s.") % line.product_id.display_name)
        if self.requires_manager_approval and not self.manager_id:
            raise ValidationError(_("Manager approval is required for this return because it exceeds the authorization threshold or requires manager pricing."))

        if self.name == '/':
            seq = self.env['ir.sequence'].next_by_code('pos.retail.customer.refund')
            self.name = seq or f"CR/{fields.Date.today().year}/{self.id:05d}"
        self.state = 'confirmed'

    def action_process(self):
        self.ensure_one()
        if self.state != 'confirmed':
            self.action_confirm()

        # Capture snapshot of previous balance
        self.previous_outstanding = self.partner_id.pos_outstanding_balance or 0.0

        # 1. Stock Return Movement
        self._process_stock_moves()

        # 2. Financial Settlement
        if self.refund_method in ('credit_ledger', 'adjust_outstanding'):
            self._process_credit_note()
        elif self.refund_method in ('cash', 'payment_method'):
            self._process_payment()

        # Ensure access token exists for sharing
        if not self.access_token:
            self.access_token = _get_customer_refund_token(self.env, self.id)

        self.state = 'done'
        return True

    def _process_stock_moves(self):
        self.ensure_one()
        warehouse = self.env['stock.warehouse'].search([('company_id', '=', self.company_id.id)], limit=1)
        picking_type = warehouse.in_type_id if warehouse else self.env['stock.picking.type'].search([
            ('code', '=', 'incoming'), ('company_id', '=', self.company_id.id)
        ], limit=1)
        if not picking_type:
            return

        customer_loc = self.partner_id.property_stock_customer or self.env.ref('stock.stock_location_customers')
        stock_loc = warehouse.lot_stock_id if warehouse else picking_type.default_location_dest_id
        scrap_loc = self.env['stock.location'].search([
            ('scrap_location', '=', True),
            ('company_id', 'in', (self.company_id.id, False)),
        ], limit=1) or stock_loc

        moves_vals = []
        for line in self.line_ids:
            dest_loc = scrap_loc if line.product_condition in ('damaged', 'defective') else stock_loc
            moves_vals.append({
                'name': f"Customer Return: {self.name} - {line.product_id.name}",
                'product_id': line.product_id.id,
                'product_uom': line.uom_id.id or line.product_id.uom_id.id,
                'product_uom_qty': line.quantity,
                'location_id': customer_loc.id,
                'location_dest_id': dest_loc.id,
                'company_id': self.company_id.id,
                'origin': self.name,
            })

        if moves_vals:
            picking = self.env['stock.picking'].create({
                'picking_type_id': picking_type.id,
                'partner_id': self.partner_id.id,
                'location_id': customer_loc.id,
                'location_dest_id': stock_loc.id,
                'origin': self.name,
                'company_id': self.company_id.id,
                'move_ids': [(0, 0, mv) for mv in moves_vals],
            })
            picking.action_confirm()
            for mv in picking.move_ids:
                mv.quantity = mv.product_uom_qty
                mv.picked = True
            try:
                picking._action_done()
            except Exception:
                pass
            self.picking_id = picking.id

    def _process_credit_note(self):
        self.ensure_one()
        invoice_lines = []
        for line in self.line_ids:
            invoice_lines.append((0, 0, {
                'product_id': line.product_id.id,
                'quantity': line.quantity,
                'price_unit': line.price_unit,
                'discount': line.discount,
                'name': f"Refund: {line.product_id.display_name} ({line.return_reason_id.name})",
            }))

        credit_note = self.env['account.move'].create({
            'move_type': 'out_refund',
            'partner_id': self.partner_id.id,
            'invoice_date': self.date.date(),
            'company_id': self.company_id.id,
            'ref': self.name,
            'invoice_line_ids': invoice_lines,
        })
        credit_note.action_post()
        self.credit_note_id = credit_note.id

        # If adjust outstanding, reconcile against oldest outstanding debt (FIFO)
        if self.refund_method == 'adjust_outstanding':
            try:
                credit_lines = credit_note.line_ids.filtered(
                    lambda l: l.account_id.account_type == 'asset_receivable' and not l.reconciled
                )
                open_debit_lines = self.env['account.move.line'].search([
                    ('partner_id', '=', self.partner_id.id),
                    ('account_id.account_type', '=', 'asset_receivable'),
                    ('move_id.move_type', 'in', ('out_invoice', 'entry')),
                    ('move_id.state', '=', 'posted'),
                    ('reconciled', '=', False),
                    ('debit', '>', 0),
                    ('company_id', '=', self.company_id.id),
                ], order='date asc, id asc')
                if credit_lines and open_debit_lines:
                    (credit_lines | open_debit_lines).reconcile()
            except Exception:
                pass

    def _process_payment(self):
        self.ensure_one()
        if not self.journal_id:
            journal = self.env['account.journal'].search([
                ('company_id', '=', self.company_id.id),
                ('type', 'in', ('cash', 'bank')),
            ], limit=1)
            self.journal_id = journal

        if self.journal_id:
            payment = self.env['account.payment'].create({
                'payment_type': 'outbound',
                'partner_type': 'customer',
                'partner_id': self.partner_id.id,
                'amount': self.amount_total,
                'date': self.date.date(),
                'journal_id': self.journal_id.id,
                'memo': f"Customer Refund: {self.name}",
                'company_id': self.company_id.id,
            })
            payment.action_post()
            self.payment_id = payment.id

    def action_cancel(self):
        self.ensure_one()
        if self.state == 'done':
            raise UserError(_("Processed refunds cannot be cancelled. Reverse via adjustment."))
        self.state = 'cancel'

    def action_print_receipt(self):
        self.ensure_one()
        return self.env.ref('pos_retail.action_report_customer_refund_receipt').report_action(self)

    def action_share_whatsapp(self):
        self.ensure_one()
        if not self.partner_id.phone and not self.partner_id.mobile:
            raise UserError(_("Customer does not have a phone or mobile number set."))
        phone = (self.partner_id.mobile or self.partner_id.phone).replace(' ', '').replace('-', '').replace('+', '')
        url = self.get_public_pdf_url()
        branch_name = self.company_id.name or "Store"
        currency = self.currency_id.symbol or "Rs."

        message = (
            f"*{branch_name}*\n"
            f"*CUSTOMER REFUND RECEIPT*\n"
            f"Refund No: {self.name}\n"
            f"Date: {self.date.strftime('%d/%m/%Y %H:%M')}\n"
            f"Customer: {self.partner_id.name}\n"
            f"Total Refund: {currency} {self.amount_total:,.2f}\n"
            f"Settlement: {dict(self._fields['refund_method'].selection).get(self.refund_method, self.refund_method)}\n"
        )
        if self.refund_method in ('credit_ledger', 'adjust_outstanding'):
            message += (
                f"Previous Balance: {currency} {self.previous_outstanding:,.2f}\n"
                f"*New Balance Owed: {currency} {self.new_outstanding:,.2f}*\n"
            )
        message += f"\nDownload Official PDF Receipt:\n{url}\n\nThank you!"

        whatsapp_url = f"https://api.whatsapp.com/send?phone={phone}&text={quote_plus(message)}"
        return {
            'type': 'ir.actions.act_url',
            'url': whatsapp_url,
            'target': 'new',
        }


class PosRetailCustomerRefundItem(models.Model):
    _name = 'pos.retail.customer.refund.item'
    _description = "Customer Refund Line Item"

    refund_id = fields.Many2one(
        'pos.retail.customer.refund',
        string="Customer Refund",
        required=True,
        ondelete='cascade',
        index=True,
    )
    product_id = fields.Many2one(
        'product.product',
        string="Product",
        required=True,
    )
    uom_id = fields.Many2one(
        'uom.uom',
        string="Unit of Measure",
    )
    quantity = fields.Float(
        string="Return Qty",
        default=1.0,
        required=True,
    )
    price_unit = fields.Float(
        string="Refund Unit Price",
        required=True,
    )
    discount = fields.Float(
        string="Discount %",
        default=0.0,
    )
    subtotal = fields.Monetary(
        string="Subtotal",
        compute='_compute_subtotal',
        store=True,
        currency_field='currency_id',
    )
    currency_id = fields.Many2one(
        'res.currency',
        related='refund_id.currency_id',
    )
    return_reason_id = fields.Many2one(
        'pos.retail.return.reason',
        string="Return Reason",
        required=True,
    )
    reason_note = fields.Char(string="Reason Details")
    product_condition = fields.Selection(
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
        required=True,
    )
    original_pos_line_id = fields.Many2one(
        'pos.order.line',
        string="Original POS Line",
    )

    @api.onchange('product_id')
    def _onchange_product_id(self):
        if self.product_id:
            self.uom_id = self.product_id.uom_id
            policy = self.refund_id.pricing_policy or 'current_price'
            if policy == 'cost':
                self.price_unit = self.product_id.standard_price
            else:
                self.price_unit = self.product_id.lst_price

    @api.depends('quantity', 'price_unit', 'discount')
    def _compute_subtotal(self):
        for line in self:
            price = line.price_unit * (1 - (line.discount or 0.0) / 100.0)
            line.subtotal = line.quantity * price
