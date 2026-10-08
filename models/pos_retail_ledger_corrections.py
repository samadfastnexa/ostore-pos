"""Correct a khata entry from the ledger itself -- both ledgers, the same way.

Both ledgers already had Edit and Reverse on each row, but they opened the
accounting screens: the journal entry form, the reversal wizard. An accountant
could use them; the shop manager who made the mistake got an access error. And
there was nothing at all for the commonest mistake, an entry made on the wrong
side (a vendor's balance typed in as a customer's).

Three corrections, on adjustment and payment rows of the Customer Ledger and
the Vendor Ledger alike, each a plain question rather than an accounting form:

  Edit                 change the amount, the direction, the date or the note
  Cancel Entry         take a mistaken entry out of the ledger
  Move to Vendor /     the entry was made on the wrong side: put it on the
  Move to Customer     other ledger, same amount, same date, same cash account

Sales, till sales, invoices and bills are not corrected here: they have
goods and stock behind them and are reversed with a refund or a return.

"The balance goes up" is a debit on the customer's receivable and a credit on
the vendor's payable, so moving an adjustment across swaps debit and credit on
every line as well as changing the account; moving a payment turns money
received from a customer into money paid to a vendor, which also puts the cash
account right -- a vendor payment typed in as "payment received" had the cash
coming in when it had gone out.
"""

from odoo import _, api, fields, models
from odoo.exceptions import UserError

from .pos_retail_ledger_sides import SIDES, check_may_enter as _check_may_correct

RELOAD = {'type': 'ir.actions.client', 'tag': 'soft_reload'}


def _entry(line, side):
    """(journal entry, payment or empty, 'payment' | 'adjustment') behind a ledger row."""
    line.ensure_one()
    env = line.env
    move = line.move_id.sudo()
    if not move:
        raise UserError(_("There is no journal entry behind this line."))
    payment = move.origin_payment_id
    if payment:
        return move, payment, 'payment'
    from_till = 'pos.session' in env and env['pos.session'].sudo().search_count([('move_id', '=', move.id)], limit=1)
    if move.move_type != 'entry' or from_till or line.transaction_type != 'adjustment':
        raise UserError(_(
            "Only khata adjustments and payments can be corrected here.\n\n"
            "%(entry)s is a sale, a till entry, an invoice or a bill: it has goods behind it, "
            "so it is corrected with a refund or a return, not by editing the ledger.",
            entry=move.name or line.move_name or ''))
    return move, payment, 'adjustment'


def _check_plain_currency(move):
    """These corrections rewrite amounts in the company currency only."""
    if any(l.currency_id and l.currency_id != move.company_currency_id for l in move.line_ids):
        raise UserError(_("%(entry)s is in a foreign currency; correct it in Accounting.", entry=move.name))


def _side_lines(move, partner, side):
    return move.line_ids.filtered(
        lambda l: l.partner_id == partner and l.account_id.account_type == SIDES[side]['account_type'])


def _reconcile_open(env, partner, side, company):
    """Match payments to the oldest open entries again, as the wizards do."""
    lines = env['account.move.line'].sudo().search([
        ('partner_id', '=', partner.id), ('account_id.account_type', '=', SIDES[side]['account_type']),
        ('parent_state', '=', 'posted'), ('reconciled', '=', False), ('company_id', '=', company.id),
    ], order='date asc, id asc')
    for account in lines.account_id:
        open_lines = lines.filtered(lambda l: l.account_id == account)
        if any(l.debit > 0 for l in open_lines) and any(l.credit > 0 for l in open_lines):
            try:
                with env.cr.savepoint():
                    open_lines.reconcile()
            except UserError:
                pass  # the balance is right either way; matching can be done by hand


def _refresh_customer_rank(env, partner):
    """A vendor with nothing left on the customer side is a vendor only again.

    Odoo marked him a customer when the wrong entry was posted; without this he
    would keep the customer buttons, and the next mistake would be allowed.
    """
    partner = partner.sudo()
    if not (partner.supplier_rank and partner.customer_rank):
        return
    if env['account.move.line'].sudo().search_count([
            ('partner_id', '=', partner.id), ('account_id.account_type', '=', 'asset_receivable'),
            ('parent_state', '=', 'posted')], limit=1):
        return
    if 'pos.order' in env and env['pos.order'].sudo().search_count([('partner_id', '=', partner.id)], limit=1):
        return
    partner.customer_rank = 0


def _cancel_entry(line, side):
    env = line.env
    _check_may_correct(env, side)
    move, payment, _kind = _entry(line, side)
    partner, company = line.partner_id.sudo(), move.company_id
    # Cancelled, not deleted: the entry stays in the books marked cancelled and
    # leaves the ledger. (Never via draft for a payment -- Odoo deletes a
    # payment's draft entry on cancel, and refuses unless it is the last number.)
    if payment:
        payment.action_cancel()
    else:
        move.button_cancel()
    _reconcile_open(env, partner, side, company)
    _refresh_customer_rank(env, partner)
    return RELOAD


def _move_entry(line, side):
    """Put an entry made on the wrong side onto the other ledger."""
    env = line.env
    other = SIDES[side]['other']
    _check_may_correct(env, side)
    _check_may_correct(env, other)
    move, payment, _kind = _entry(line, side)
    partner, company = line.partner_id.sudo(), move.company_id
    target_account = partner.with_company(company)[SIDES[other]['property']]
    if not target_account:
        raise UserError(_("%(name)s has no account set for the other ledger.", name=partner.display_name))
    if payment:
        values = {
            'payment_type': SIDES[other]['payment_type'], 'partner_type': SIDES[other]['partner_type'],
            'partner_id': partner.id, 'amount': payment.amount, 'currency_id': payment.currency_id.id,
            'journal_id': payment.journal_id.id, 'date': payment.date, 'memo': payment.memo,
            'company_id': company.id,
        }
        payment.action_cancel()
        env['account.payment'].sudo().with_company(company).create(values).action_post()
    else:
        wrong = _side_lines(move, partner, side)
        _check_plain_currency(move)
        move.button_draft()
        # balance and amount_currency together: flipping debit/credit alone
        # leaves the currency amount with the old sign, which Odoo refuses.
        move.write({'line_ids': [
            (1, l.id, dict({'balance': -l.balance, 'amount_currency': -l.amount_currency},
                           **({'account_id': target_account.id} if l in wrong else {})))
            for l in move.line_ids]})
        move.action_post()
    if other == 'vendor':
        if not partner.supplier_rank:
            partner.supplier_rank = 1
        _refresh_customer_rank(env, partner)
    elif not partner.customer_rank:
        partner.customer_rank = 1
    _reconcile_open(env, partner, other, company)
    _reconcile_open(env, partner, side, company)
    return RELOAD


def _open_edit(line, side):
    _check_may_correct(line.env, side)
    move, _payment, _kind = _entry(line, side)
    return {
        'type': 'ir.actions.act_window',
        'name': _("Edit Khata Entry"),
        'res_model': 'pos.retail.ledger.entry.edit',
        'view_mode': 'form',
        'target': 'new',
        'context': {'default_move_id': move.id, 'default_side': side, 'default_partner_id': line.partner_id.id},
    }


class PosRetailCustomerLedgerLine(models.Model):
    _inherit = 'pos.retail.customer.ledger.line'

    def action_edit_entry(self):
        return _open_edit(self, 'customer')

    def action_reverse_entry(self):
        return _cancel_entry(self, 'customer')

    def action_move_to_other_ledger(self):
        return _move_entry(self, 'customer')


class PosRetailVendorLedgerLine(models.Model):
    _inherit = 'pos.retail.vendor.ledger.line'

    def action_edit_entry(self):
        return _open_edit(self, 'vendor')

    def action_reverse_entry(self):
        return _cancel_entry(self, 'vendor')

    def action_move_to_other_ledger(self):
        return _move_entry(self, 'vendor')

    def action_pay_vendor(self):
        """Pay Vendor, the twin of Receive Payment on the customer ledger."""
        partner = self.mapped('partner_id')[:1]
        return {
            'type': 'ir.actions.act_window',
            'name': _("Pay Vendor"),
            'res_model': 'pos.retail.vendor.payment',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_partner_id': partner.id if partner else False},
        }


class PosRetailLedgerEntryEdit(models.TransientModel):
    """Edit one khata adjustment or payment in place: amount, direction, date, note."""
    _name = 'pos.retail.ledger.entry.edit'
    _description = "Edit Khata Entry"

    move_id = fields.Many2one('account.move', string="Entry", required=True, readonly=True)
    side = fields.Selection([('customer', "Customer khata"), ('vendor', "Vendor khata")],
                            string="Ledger", required=True, readonly=True)
    partner_id = fields.Many2one('res.partner', string="Contact", required=True, readonly=True)
    kind = fields.Selection([('adjustment', "Khata adjustment"), ('payment', "Payment")],
                            string="Entry Type", required=True, readonly=True)
    currency_id = fields.Many2one('res.currency', readonly=True)
    direction = fields.Selection(
        [('increase', "Balance goes UP (owes more)"), ('decrease', "Balance goes DOWN (owes less)")],
        string="Effect on the Khata",
        help="UP: the customer owes the shop more, or the shop owes the vendor more. "
             "DOWN: the opposite. A payment always takes the balance down.")
    amount = fields.Monetary(required=True, currency_field='currency_id')
    date = fields.Date(required=True)
    reason = fields.Char(string="Note")

    @api.model
    def default_get(self, fields_list):
        values = super().default_get(fields_list)
        move = self.env['account.move'].sudo().browse(values.get('move_id') or self.env.context.get('default_move_id'))
        side = values.get('side') or self.env.context.get('default_side')
        partner = self.env['res.partner'].sudo().browse(
            values.get('partner_id') or self.env.context.get('default_partner_id'))
        if not move.exists() or side not in SIDES or not partner:
            return values
        payment = move.origin_payment_id
        values.update(currency_id=move.company_id.currency_id.id)
        if payment:
            values.update(kind='payment', amount=payment.amount, date=payment.date,
                          reason=payment.memo or '', direction='decrease')
        else:
            line = _side_lines(move, partner, side)[:1]
            up = bool(line.debit) if side == 'customer' else bool(line.credit)
            values.update(kind='adjustment', amount=max(line.debit, line.credit), date=move.date,
                          reason=move.ref or line.name or '', direction='increase' if up else 'decrease')
        return values

    def action_confirm(self):
        self.ensure_one()
        _check_may_correct(self.env, self.side)
        if self.amount <= 0:
            raise UserError(_("The amount must be more than zero. To remove the entry, use Cancel Entry."))
        move = self.move_id.sudo()
        partner, company = self.partner_id.sudo(), move.company_id
        payment = move.origin_payment_id
        if payment:
            payment.action_draft()
            payment.write({'amount': self.amount, 'date': self.date, 'memo': self.reason or payment.memo})
            payment.action_post()
        else:
            own = _side_lines(move, partner, self.side)
            if len(own) != 1 or len(move.line_ids) != 2:
                raise UserError(_(
                    "%(entry)s has more than two lines, so it cannot be edited here. Cancel it and "
                    "enter it again.", entry=move.name))
            _check_plain_currency(move)
            up = self.direction == 'increase'
            # Up is a debit (+) on the customer's receivable, a credit (-) on
            # the vendor's payable; the other line always mirrors it.
            own_sign = 1 if up == (self.side == 'customer') else -1
            move.button_draft()
            move.write({
                'date': self.date,
                'ref': self.reason or move.ref,
                'line_ids': [(1, l.id, {
                    'name': self.reason or l.name,
                    'balance': self.amount * (own_sign if l == own else -own_sign),
                    'amount_currency': self.amount * (own_sign if l == own else -own_sign),
                }) for l in move.line_ids],
            })
            move.action_post()
        _reconcile_open(self.env, partner, self.side, company)
        return RELOAD
