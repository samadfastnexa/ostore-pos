# -*- coding: utf-8 -*-
import hashlib
import hmac
import pytz
from urllib.parse import quote_plus

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError


def _get_vendor_return_token(env, return_id):
    secret = env['ir.config_parameter'].sudo().get_param('database.secret', 'pos_retail_khata')
    msg = f'vendor_return_{return_id}'.encode('utf-8')
    return hmac.new(secret.encode('utf-8'), msg, hashlib.sha256).hexdigest()[:16]


class PosRetailVendorReturn(models.Model):
    _name = 'pos.retail.vendor.return'
    _description = "Vendor Return"
    _order = 'date desc, id desc'
    _inherit = ['mail.thread', 'mail.activity.mixin']

    name = fields.Char(
        string="Return Reference",
        required=True,
        copy=False,
        readonly=True,
        default='/',
        index=True,
    )
    partner_id = fields.Many2one(
        'res.partner',
        string="Vendor",
        required=True,
        tracking=True,
        index=True,
    )
    partner_payable = fields.Monetary(
        string="Current Net Payable Owed",
        compute='_compute_partner_payable',
        currency_field='currency_id',
    )
    date = fields.Datetime(
        string="Return Date",
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
        string="Created By",
        default=lambda self: self.env.user,
        required=True,
    )
    return_type = fields.Selection(
        [
            ('no_po', "Quick Return (No PO)"),
            ('po_linked', "Purchase Order Linked"),
        ],
        string="Return Mode",
        default='no_po',
        required=True,
    )
    purchase_order_id = fields.Many2one(
        'purchase.order',
        string="Original Purchase Order",
    )
    vendor_bill_id = fields.Many2one(
        'account.move',
        string="Original Vendor Bill",
    )
    vendor_reference = fields.Char(
        string="Vendor Bill / PO Reference",
    )
    settlement_method = fields.Selection(
        [
            ('cash', "Cash Refund"),
            ('bank', "Bank Transfer / Refund"),
            ('vendor_credit', "Vendor Credit Note (Store Credit)"),
            ('adjust_payable', "Adjust Against Payable Debt"),
        ],
        string="Settlement Option",
        default='adjust_payable',
        required=True,
        tracking=True,
    )
    journal_id = fields.Many2one(
        'account.journal',
        string="Settlement Journal",
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
        'pos.retail.vendor.return.item',
        'vendor_return_id',
        string="Return Lines",
        copy=True,
    )
    amount_total = fields.Monetary(
        string="Total Return Value",
        compute='_compute_amounts',
        store=True,
        currency_field='currency_id',
        tracking=True,
    )
    previous_payable = fields.Monetary(
        string="Previous Payable Balance",
        currency_field='currency_id',
    )
    new_payable = fields.Monetary(
        string="New Payable Balance",
        compute='_compute_amounts',
        store=True,
        currency_field='currency_id',
    )
    picking_id = fields.Many2one(
        'stock.picking',
        string="Outgoing Return Transfer",
        readonly=True,
        copy=False,
    )
    credit_note_id = fields.Many2one(
        'account.move',
        string="Vendor Credit Note (Debit Note)",
        readonly=True,
        copy=False,
    )
    payment_id = fields.Many2one(
        'account.payment',
        string="Vendor Refund Payment",
        readonly=True,
        copy=False,
    )
    notes = fields.Text(string="Internal Notes")
    access_token = fields.Char(string="Access Token", copy=False)

    @api.depends('partner_id')
    def _compute_partner_payable(self):
        for rec in self:
            rec.partner_payable = -rec.partner_id.credit if rec.partner_id else 0.0

    @api.depends('line_ids.subtotal', 'settlement_method', 'previous_payable', 'state')
    def _compute_amounts(self):
        for rec in self:
            total = sum(rec.line_ids.mapped('subtotal'))
            rec.amount_total = total
            if rec.settlement_method in ('vendor_credit', 'adjust_payable'):
                rec.new_payable = rec.previous_payable - total
            else:
                rec.new_payable = rec.previous_payable

    def get_public_pdf_url(self):
        self.ensure_one()
        if not self.access_token:
            self.access_token = _get_vendor_return_token(self.env, self.id)
        base_url = self.env['ir.config_parameter'].sudo().get_param('web.base.url', '')
        return f"{base_url}/pos_retail/portal/vendor_return/pdf/{self.id}?token={self.access_token}"

    def action_confirm(self):
        self.ensure_one()
        if not self.line_ids:
            raise UserError(_("Please add at least one product line to return."))
        for line in self.line_ids:
            if line.quantity <= 0:
                raise ValidationError(_("Return quantity must be greater than zero for %s.") % line.product_id.display_name)
            if line.return_reason_id.name and 'other' in line.return_reason_id.name.lower() and not line.reason_note:
                raise ValidationError(_("Please provide a note for the 'Other' return reason on line %s.") % line.product_id.display_name)

        if self.name == '/':
            seq = self.env['ir.sequence'].next_by_code('pos.retail.vendor.return')
            self.name = seq or f"VR/{fields.Date.today().year}/{self.id:05d}"
        self.state = 'confirmed'

    def action_process(self):
        self.ensure_one()
        if self.state != 'confirmed':
            self.action_confirm()

        # Capture snapshot of previous payable debt
        self.previous_payable = -self.partner_id.credit or 0.0

        # 1. Outgoing Stock Transfer to Supplier
        self._process_stock_moves()

        # 2. Financial Settlement
        if self.settlement_method in ('vendor_credit', 'adjust_payable'):
            self._process_credit_note()
        elif self.settlement_method in ('cash', 'bank'):
            self._process_payment()

        if not self.access_token:
            self.access_token = _get_vendor_return_token(self.env, self.id)

        self.state = 'done'
        return True

    def _process_stock_moves(self):
        self.ensure_one()
        warehouse = self.env['stock.warehouse'].search([('company_id', '=', self.company_id.id)], limit=1)
        picking_type = warehouse.out_type_id if warehouse else self.env['stock.picking.type'].search([
            ('code', '=', 'outgoing'), ('company_id', '=', self.company_id.id)
        ], limit=1)
        if not picking_type:
            return

        supplier_loc = self.partner_id.property_stock_supplier or self.env.ref('stock.stock_location_suppliers')
        stock_loc = warehouse.lot_stock_id if warehouse else picking_type.default_location_src_id
        scrap_loc = self.env['stock.location'].search([
            ('scrap_location', '=', True),
            ('company_id', 'in', (self.company_id.id, False)),
        ], limit=1) or stock_loc

        moves_vals = []
        for line in self.line_ids:
            src_loc = scrap_loc if line.product_condition in ('damaged', 'defective') else stock_loc
            moves_vals.append({
                'name': f"Vendor Return: {self.name} - {line.product_id.name}",
                'product_id': line.product_id.id,
                'product_uom': line.uom_id.id or line.product_id.uom_id.id,
                'product_uom_qty': line.quantity,
                'location_id': src_loc.id,
                'location_dest_id': supplier_loc.id,
                'company_id': self.company_id.id,
                'origin': self.name,
            })

        if moves_vals:
            picking = self.env['stock.picking'].create({
                'picking_type_id': picking_type.id,
                'partner_id': self.partner_id.id,
                'location_id': stock_loc.id,
                'location_dest_id': supplier_loc.id,
                'origin': self.name,
                'company_id': self.company_id.id,
                'pos_retail_vendor_return_reason_id': self.line_ids[0].return_reason_id.id if self.line_ids else False,
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
        bill_lines = []
        for line in self.line_ids:
            bill_lines.append((0, 0, {
                'product_id': line.product_id.id,
                'quantity': line.quantity,
                'price_unit': line.price_unit,
                'name': f"Vendor Return: {line.product_id.display_name} ({line.return_reason_id.name})",
            }))

        credit_note = self.env['account.move'].create({
            'move_type': 'in_refund',
            'partner_id': self.partner_id.id,
            'invoice_date': self.date.date(),
            'company_id': self.company_id.id,
            'ref': self.name,
            'invoice_line_ids': bill_lines,
        })
        credit_note.action_post()
        self.credit_note_id = credit_note.id

        # If adjust payable, reconcile against oldest vendor bills (FIFO)
        if self.settlement_method == 'adjust_payable':
            try:
                credit_lines = credit_note.line_ids.filtered(
                    lambda l: l.account_id.account_type == 'liability_payable' and not l.reconciled
                )
                open_payable_lines = self.env['account.move.line'].search([
                    ('partner_id', '=', self.partner_id.id),
                    ('account_id.account_type', '=', 'liability_payable'),
                    ('move_id.move_type', 'in', ('in_invoice', 'entry')),
                    ('move_id.state', '=', 'posted'),
                    ('reconciled', '=', False),
                    ('credit', '>', 0),
                    ('company_id', '=', self.company_id.id),
                ], order='date asc, id asc')
                if credit_lines and open_payable_lines:
                    (credit_lines | open_payable_lines).reconcile()
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
                'payment_type': 'inbound',
                'partner_type': 'supplier',
                'partner_id': self.partner_id.id,
                'amount': self.amount_total,
                'date': self.date.date(),
                'journal_id': self.journal_id.id,
                'memo': f"Vendor Return Refund: {self.name}",
                'company_id': self.company_id.id,
            })
            payment.action_post()
            self.payment_id = payment.id

    def action_cancel(self):
        self.ensure_one()
        if self.state == 'done':
            raise UserError(_("Processed vendor returns cannot be cancelled."))
        self.state = 'cancel'

    def action_print_receipt(self):
        self.ensure_one()
        return self.env.ref('pos_retail.action_report_vendor_return_receipt').report_action(self)

    def action_share_whatsapp(self):
        self.ensure_one()
        if not self.partner_id.phone and not self.partner_id.mobile:
            raise UserError(_("Vendor does not have a phone or mobile number set."))
        phone = (self.partner_id.mobile or self.partner_id.phone).replace(' ', '').replace('-', '').replace('+', '')
        url = self.get_public_pdf_url()
        branch_name = self.company_id.name or "Store"
        currency = self.currency_id.symbol or "Rs."

        dt = self.date
        if dt:
            tz = pytz.timezone('Asia/Karachi')
            dt_utc = pytz.utc.localize(dt) if not dt.tzinfo else dt
            date_str = dt_utc.astimezone(tz).strftime('%d/%m/%Y %H:%M')
        else:
            date_str = ''

        message = (
            f"*{branch_name}*\n"
            f"*VENDOR RETURN RECEIPT / DEBIT NOTE*\n"
            f"Return Ref: {self.name}\n"
            f"Date: {date_str}\n"
            f"Vendor: {self.partner_id.name}\n"
            f"Total Return Value: {currency} {self.amount_total:,.2f}\n"
            f"Settlement: {dict(self._fields['settlement_method'].selection).get(self.settlement_method, self.settlement_method)}\n"
        )
        if self.settlement_method in ('vendor_credit', 'adjust_payable'):
            message += (
                f"Previous Payable: {currency} {self.previous_payable:,.2f}\n"
                f"*New Balance Payable: {currency} {self.new_payable:,.2f}*\n"
            )
        if self.line_ids:
            message += "\n*Returned Items:*\n"
            for line in self.line_ids:
                message += f"• {line.qty_returned} x {line.product_id.display_name} - {currency} {line.subtotal:,.2f}\n"

        message += f"\n📄 *Download Official Return Receipt & Debit Note PDF:*\n{url}\n\nThank you!"

        whatsapp_url = f"https://api.whatsapp.com/send?phone={phone}&text={quote_plus(message)}"
        return {
            'type': 'ir.actions.act_url',
            'url': whatsapp_url,
            'target': 'new',
        }


class PosRetailVendorReturnItem(models.Model):
    _name = 'pos.retail.vendor.return.item'
    _description = "Vendor Return Line Item"

    vendor_return_id = fields.Many2one(
        'pos.retail.vendor.return',
        string="Vendor Return",
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
        string="Unit Cost / Price",
        required=True,
    )
    subtotal = fields.Monetary(
        string="Subtotal",
        compute='_compute_subtotal',
        store=True,
        currency_field='currency_id',
    )
    currency_id = fields.Many2one(
        'res.currency',
        related='vendor_return_id.currency_id',
    )
    return_reason_id = fields.Many2one(
        'pos.retail.vendor.return.reason',
        string="Return Reason",
        required=True,
    )
    reason_note = fields.Char(string="Reason Details")
    product_condition = fields.Selection(
        [
            ('resalable', "Resalable / Excess"),
            ('damaged', "Damaged in Transit"),
            ('defective', "Defective / Faulty"),
            ('expired', "Expired"),
            ('packaging_missing', "Packaging Damaged / Missing"),
            ('other', "Other"),
        ],
        string="Product Condition",
        default='defective',
        required=True,
    )
    purchase_line_id = fields.Many2one(
        'purchase.order.line',
        string="Original Purchase Line",
    )

    @api.onchange('product_id')
    def _onchange_product_id(self):
        if self.product_id:
            self.uom_id = self.product_id.uom_id
            self.price_unit = self.product_id.standard_price

    @api.depends('quantity', 'price_unit')
    def _compute_subtotal(self):
        for line in self:
            line.subtotal = line.quantity * line.price_unit
