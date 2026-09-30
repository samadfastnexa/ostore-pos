# -*- coding: utf-8 -*-
import datetime
import hashlib
import hmac
import pytz
from odoo import _, api, fields, models
from odoo.exceptions import UserError


class PosRetailVendor(models.Model):
    _inherit = 'res.partner'

    @api.model
    def pos_retail_search_vendors(self, query='', config_id=False, limit=80):
        """Search vendors for POS till with real-time payable balances and aggregates.

        Filtered to suppliers (supplier_rank > 0 or partners with purchase orders/payable lines).
        Multi-company aware: respects the active till's company structure.
        """
        config = self.env['pos.config'].sudo().browse(int(config_id)).exists() if config_id else False
        company = config.company_id if config else self.env.company
        currency = company.currency_id

        domain = [
            ('supplier_rank', '>', 0),
            ('employee', '=', False),
        ]

        if company:
            c_ids = [company.id]
            if company.parent_id:
                c_ids.append(company.parent_id.id)
            domain.append(('company_id', 'in', [False] + c_ids))

        if query and query.strip():
            q = query.strip()
            domain += [
                '|', '|', '|', '|', '|',
                ('name', 'ilike', q),
                ('phone', 'ilike', q),
                ('mobile', 'ilike', q),
                ('email', 'ilike', q),
                ('vendor_contact_person', 'ilike', q),
                ('vendor_code', 'ilike', q),
            ]

        vendors = self.sudo().search(domain, order='name asc', limit=limit)

        secret = self.env['ir.config_parameter'].sudo().get_param('database.secret', 'pos_retail_khata')
        base_url = self.get_base_url().rstrip('/')

        vendor_list = []
        total_payable = 0.0

        for p in vendors:
            # Payable journal lines: bills we owe the vendor (credit) and payments made (debit)
            pay_grouped = self.env['account.move.line'].sudo()._read_group(
                domain=[
                    ('partner_id', '=', p.id),
                    ('account_id.account_type', '=', 'liability_payable'),
                    ('parent_state', '=', 'posted'),
                ],
                aggregates=('debit:sum', 'credit:sum'),
            )
            vend_debit, vend_credit = pay_grouped[0] if pay_grouped else (0.0, 0.0)
            vend_debit = vend_debit or 0.0
            vend_credit = vend_credit or 0.0
            vend_balance = round(vend_credit - vend_debit, 2)  # Positive = shop owes vendor

            # Unpaid bills count
            unpaid_count = self.env['account.move.line'].sudo().search_count([
                ('partner_id', '=', p.id),
                ('account_id.account_type', '=', 'liability_payable'),
                ('parent_state', '=', 'posted'),
                ('credit', '>', 0),
                ('reconciled', '=', False),
                ('amount_residual', '!=', 0),
            ])

            # Purchase orders count
            po_count = self.env['purchase.order'].sudo().search_count([
                ('partner_id', 'child_of', p.id),
            ])

            # Statement security token for WhatsApp sharing
            ledger_token = hmac.new(
                secret.encode('utf-8'),
                f'ledger_partner_{p.id}'.encode('utf-8'),
                hashlib.sha256
            ).hexdigest()[:16]

            pdf_url = f"{base_url}/pos_retail/portal/vendor/pdf/{p.id}?token={ledger_token}"

            total_payable += max(0.0, vend_balance)

            vendor_list.append({
                'id': p.id,
                'name': p.name,
                'display_name': p.display_name,
                'phone': p.phone or '',
                'mobile': p.mobile or '',
                'contact_phone': p.mobile or p.phone or '',
                'email': p.email or '',
                'vendor_contact_person': p.vendor_contact_person or '',
                'vendor_code': p.vendor_code or '',
                'street': p.street or '',
                'city': p.city or '',
                'vendor_status': p.vendor_status or 'active',
                'balance': vend_balance,
                'balance_formatted': currency.format(vend_balance),
                'bills_total': vend_credit,
                'bills_total_formatted': currency.format(vend_credit),
                'paid_total': vend_debit,
                'paid_total_formatted': currency.format(vend_debit),
                'unpaid_bills_count': unpaid_count,
                'po_count': po_count,
                'ledger_token': ledger_token,
                'pdf_url': pdf_url,
            })

        return {
            'vendors': vendor_list,
            'total_vendors': len(vendor_list),
            'total_payable': total_payable,
            'total_payable_formatted': currency.format(total_payable),
            'currency_symbol': currency.symbol or 'Rs.',
        }

    @api.model
    def pos_retail_create_vendor(self, vals, config_id=False, employee_id=False):
        """Create a new vendor directly from the POS till counter.

        Allows cashiers to immediately register a new vendor with optional
        contact person, phone, mobile, address, and opening khata balance brought forward.
        """
        name = (vals.get('name') or '').strip()
        if not name:
            raise UserError(_("Vendor name is required."))

        config = self.env['pos.config'].sudo().browse(int(config_id)).exists() if config_id else False
        company = config.company_id if config else self.env.company
        currency = company.currency_id

        employee = self.env['hr.employee'].sudo().browse(int(employee_id)).exists() if employee_id else False
        cashier_name = employee.name if employee else self.env.user.name

        vendor_vals = {
            'name': name,
            'is_company': vals.get('is_company', True),
            'supplier_rank': 1,
            'customer_rank': 0,
            'vendor_contact_person': (vals.get('vendor_contact_person') or '').strip(),
            'vendor_code': (vals.get('vendor_code') or '').strip(),
            'phone': (vals.get('phone') or '').strip(),
            'mobile': (vals.get('mobile') or '').strip(),
            'email': (vals.get('email') or '').strip(),
            'street': (vals.get('street') or '').strip(),
            'city': (vals.get('city') or '').strip(),
            'comment': (vals.get('notes') or '').strip(),
            'company_id': company.id,
        }

        # Auto vendor code if empty
        if not vendor_vals['vendor_code']:
            vendor_vals['vendor_code'] = f"VND-{company.id}-{int(fields.Datetime.now().timestamp()) % 100000:05d}"

        partner = self.sudo().with_company(company).create(vendor_vals)

        # Handle opening khata balance if specified
        opening_balance = float(vals.get('opening_balance') or 0.0)
        if opening_balance > 0:
            # Shop owes vendor initial balance:
            # Credit partner payable account, Debit equity / capital account
            payable_acc = partner.property_account_payable_id
            if not payable_acc:
                raise UserError(_("No payable account configured for company %s", company.name))

            equity_acc = self.env['account.account'].with_company(company).search(
                [('account_type', '=', 'equity')], limit=1
            )
            if not equity_acc:
                equity_acc = self.env['account.account'].with_company(company).search(
                    [('account_type', 'not in', ('asset_receivable', 'liability_payable'))], limit=1
                )

            misc_journal = self._pos_retail_get_misc_journal(company)
            reason = _("Opening Balance / Paper Khata (Added at till by %s)", cashier_name)

            move = self.env['account.move'].sudo().with_company(company).create({
                'move_type': 'entry',
                'journal_id': misc_journal.id,
                'company_id': company.id,
                'date': fields.Date.context_today(self),
                'ref': reason,
                'line_ids': [
                    (0, 0, {
                        'partner_id': partner.id,
                        'account_id': payable_acc.id,
                        'name': reason,
                        'debit': 0.0,
                        'credit': opening_balance,
                    }),
                    (0, 0, {
                        'partner_id': partner.id,
                        'account_id': equity_acc.id,
                        'name': reason,
                        'debit': opening_balance,
                        'credit': 0.0,
                    }),
                ],
            })
            move.action_post()

        self.env.flush_all()

        # Build response representation
        secret = self.env['ir.config_parameter'].sudo().get_param('database.secret', 'pos_retail_khata')
        base_url = self.get_base_url().rstrip('/')
        ledger_token = hmac.new(
            secret.encode('utf-8'),
            f'ledger_partner_{partner.id}'.encode('utf-8'),
            hashlib.sha256
        ).hexdigest()[:16]

        vend_balance = round(opening_balance, 2)

        return {
            'id': partner.id,
            'name': partner.name,
            'display_name': partner.display_name,
            'phone': partner.phone or '',
            'mobile': partner.mobile or '',
            'contact_phone': partner.mobile or partner.phone or '',
            'email': partner.email or '',
            'vendor_contact_person': partner.vendor_contact_person or '',
            'vendor_code': partner.vendor_code or '',
            'street': partner.street or '',
            'city': partner.city or '',
            'vendor_status': partner.vendor_status or 'active',
            'balance': vend_balance,
            'balance_formatted': currency.format(vend_balance),
            'bills_total': opening_balance,
            'bills_total_formatted': currency.format(opening_balance),
            'paid_total': 0.0,
            'paid_total_formatted': currency.format(0.0),
            'unpaid_bills_count': 1 if opening_balance > 0 else 0,
            'po_count': 0,
            'ledger_token': ledger_token,
            'pdf_url': f"{base_url}/pos_retail/portal/vendor/pdf/{partner.id}?token={ledger_token}",
        }

    @api.model
    def pos_retail_pay_vendor(self, partner_id, amount, config_id, employee_id,
                               journal_id=False, memo=False, payment_date=False):
        """Pay a vendor directly from the POS till (outbound payment).

        Records an account.payment of type 'outbound' against partner's payable account,
        reduces the vendor khata balance, reconciles against oldest unpaid bills,
        and generates WhatsApp sharing and printable receipt URLs.
        """
        amt = float(amount or 0.0)
        if amt <= 0:
            raise UserError(_("Please enter a payment amount greater than zero."))

        partner = self.sudo().browse(int(partner_id)).exists()
        if not partner:
            raise UserError(_("Vendor record not found."))

        config = self.env['pos.config'].sudo().browse(int(config_id)).exists() if config_id else False
        company = config.company_id if config else (partner.company_id or self.env.company)
        currency = company.currency_id

        employee = self.env['hr.employee'].sudo().browse(int(employee_id)).exists() if employee_id else False
        user = (employee and employee.user_id) or self.env.user
        cashier_name = employee.name if employee else user.name

        # Resolve payment journal
        target_journal = False
        if journal_id:
            # Check if passed ID is a pos.payment.method
            pm = self.env['pos.payment.method'].sudo().browse(int(journal_id)).exists()
            if pm and pm.journal_id:
                target_journal = pm.journal_id
            else:
                j = self.env['account.journal'].sudo().browse(int(journal_id)).exists()
                if j:
                    target_journal = j

        if not target_journal:
            # Fall back to cash or bank journal of this company
            target_journal = self.env['account.journal'].sudo().search([
                ('type', '=', 'cash'),
                ('company_id', '=', company.id),
            ], limit=1)
            if not target_journal:
                target_journal = self.env['account.journal'].sudo().search([
                    ('type', 'in', ('cash', 'bank')),
                    ('company_id', '=', company.id),
                ], limit=1)

        if not target_journal:
            raise UserError(_("No cash or bank journal found for company %s", company.name))

        if not partner.property_account_payable_id:
            raise UserError(_("Vendor %s has no payable account configured.", partner.name))

        # Get previous balance before payment
        pay_grouped = self.env['account.move.line'].sudo()._read_group(
            domain=[
                ('partner_id', '=', partner.id),
                ('account_id.account_type', '=', 'liability_payable'),
                ('parent_state', '=', 'posted'),
            ],
            aggregates=('debit:sum', 'credit:sum'),
        )
        prev_debit, prev_credit = pay_grouped[0] if pay_grouped else (0.0, 0.0)
        previous_balance = round((prev_credit or 0.0) - (prev_debit or 0.0), 2)

        note = memo or _("Vendor payment at till by %s", cashier_name)
        pay_date = payment_date or fields.Date.context_today(self)

        payment = self.env['account.payment'].sudo().with_company(company).create({
            'payment_type': 'outbound',
            'partner_type': 'supplier',
            'partner_id': partner.id,
            'amount': amt,
            'currency_id': currency.id,
            'journal_id': target_journal.id,
            'date': pay_date,
            'memo': note,
            'company_id': company.id,
        })
        payment.action_post()

        # Reconcile payment line against oldest open payable lines (FIFO)
        payable_acc = partner.property_account_payable_id
        open_lines = self.env['account.move.line'].sudo().search([
            ('partner_id', '=', partner.id),
            ('account_id', '=', payable_acc.id),
            ('parent_state', '=', 'posted'),
            ('reconciled', '=', False),
            ('company_id', '=', company.id),
        ], order='date asc, id asc')

        if len(open_lines) >= 2 and any(l.debit > 0 for l in open_lines) and any(l.credit > 0 for l in open_lines):
            try:
                open_lines.reconcile()
            except Exception:
                pass

        self.env.flush_all()

        new_balance = round(previous_balance - amt, 2)

        # PDF Receipt and Statement links
        secret = self.env['ir.config_parameter'].sudo().get_param('database.secret', 'pos_retail_khata')
        base_url = self.get_base_url().rstrip('/')
        payment_token = hmac.new(
            secret.encode('utf-8'),
            f'pos_payment_{payment.id}'.encode('utf-8'),
            hashlib.sha256
        ).hexdigest()[:16]

        receipt_pdf_url = f"{base_url}/pos_retail/portal/payment/pdf/{payment.id}?token={payment_token}"

        statement_token = hmac.new(
            secret.encode('utf-8'),
            f'ledger_partner_{partner.id}'.encode('utf-8'),
            hashlib.sha256
        ).hexdigest()[:16]
        statement_pdf_url = f"{base_url}/pos_retail/portal/vendor/pdf/{partner.id}?token={statement_token}"

        now_pak = pytz.utc.localize(datetime.datetime.utcnow()).astimezone(pytz.timezone('Asia/Karachi')).strftime('%Y-%m-%d %H:%M:%S')

        # Structured WhatsApp text
        wa_lines = [
            f"*{company.name}*",
            f"*VENDOR PAYMENT RECEIPT*",
            f"Date: {pay_date} ({now_pak})",
            f"Receipt No: *{payment.name}*",
            f"--------------------------------",
            f"*Vendor:* {partner.name}",
        ]
        if partner.phone or partner.mobile:
            wa_lines.append(f"*Phone:* {partner.mobile or partner.phone}")
        wa_lines += [
            f"*Payment Method:* {target_journal.name}",
            f"*Paid Amount:* *{currency.format(amt)}*",
            f"--------------------------------",
            f"Previous Balance: {currency.format(previous_balance)}",
            f"*Remaining Payable:* *{currency.format(new_balance)}*",
        ]
        if memo:
            wa_lines.append(f"Note: {memo}")
        wa_lines += [
            f"--------------------------------",
            f"📄 *Payment Receipt:* {receipt_pdf_url}",
            f"📊 *Full Statement:* {statement_pdf_url}",
            f"Thank you for your business!",
        ]

        return {
            'payment_id': payment.id,
            'payment_name': payment.name,
            'is_vendor': True,
            'partner_id': partner.id,
            'partner_name': partner.name,
            'partner_phone': partner.mobile or partner.phone or '',
            'paid': amt,
            'paid_formatted': currency.format(amt),
            'previous_balance': previous_balance,
            'previous_balance_formatted': currency.format(previous_balance),
            'new_balance': new_balance,
            'new_balance_formatted': currency.format(new_balance),
            'journal_name': target_journal.name,
            'memo': note,
            'date': str(pay_date),
            'datetime': now_pak,
            'cashier_name': cashier_name,
            'branch_name': company.name,
            'pdf_url': receipt_pdf_url,
            'statement_url': statement_pdf_url,
            'whatsapp_text': "\n".join(wa_lines),
        }

    @api.model
    def pos_retail_adjust_vendor_khata(self, partner_id, amount, direction, reason,
                                        config_id, employee_id, date=False):
        """Adjust a vendor's khata balance (increase or decrease what is owed).

        - 'increase': Shop owes MORE (e.g. unbilled goods received, manual balance addition).
          Credit payable account, Debit equity/expense account.
        - 'decrease': Shop owes LESS (e.g. vendor rebate, discount, return deduction, waiver).
          Debit payable account, Credit income/equity account.
        """
        amt = float(amount or 0.0)
        if amt <= 0:
            raise UserError(_("The adjustment amount must be greater than zero."))

        if direction not in ('increase', 'decrease'):
            raise UserError(_("Invalid adjustment direction."))

        reason_text = (reason or '').strip()
        if not reason_text:
            raise UserError(_("Please enter an adjustment reason / explanation."))

        partner = self.sudo().browse(int(partner_id)).exists()
        if not partner:
            raise UserError(_("Vendor record not found."))

        config = self.env['pos.config'].sudo().browse(int(config_id)).exists() if config_id else False
        company = config.company_id if config else (partner.company_id or self.env.company)
        currency = company.currency_id

        employee = self.env['hr.employee'].sudo().browse(int(employee_id)).exists() if employee_id else False
        cashier_name = employee.name if employee else self.env.user.name

        payable_acc = partner.property_account_payable_id
        if not payable_acc:
            raise UserError(_("Vendor %s has no payable account configured.", partner.name))

        # Counterpart account resolution
        Account = self.env['account.account'].with_company(company)
        if direction == 'increase':
            # Shop owes MORE: Debit Equity / Expense, Credit Payable
            counterpart = Account.search([('account_type', '=', 'equity')], limit=1) or \
                          Account.search([('account_type', '=', 'expense')], limit=1)
        else:
            # Shop owes LESS: Debit Payable, Credit Income / Expense reduction / Equity
            counterpart = Account.search([('account_type', '=', 'income')], limit=1) or \
                          Account.search([('account_type', '=', 'equity')], limit=1)

        if not counterpart:
            counterpart = Account.search([
                ('account_type', 'not in', ('asset_receivable', 'liability_payable'))
            ], limit=1)

        misc_journal = self._pos_retail_get_misc_journal(company)

        # Get previous balance
        pay_grouped = self.env['account.move.line'].sudo()._read_group(
            domain=[
                ('partner_id', '=', partner.id),
                ('account_id.account_type', '=', 'liability_payable'),
                ('parent_state', '=', 'posted'),
            ],
            aggregates=('debit:sum', 'credit:sum'),
        )
        prev_debit, prev_credit = pay_grouped[0] if pay_grouped else (0.0, 0.0)
        previous_balance = round((prev_credit or 0.0) - (prev_debit or 0.0), 2)

        entry_ref = f"{reason_text} (Till: {cashier_name})"
        adj_date = date or fields.Date.context_today(self)

        inc = direction == 'increase'
        move = self.env['account.move'].sudo().with_company(company).create({
            'move_type': 'entry',
            'journal_id': misc_journal.id,
            'company_id': company.id,
            'date': adj_date,
            'ref': entry_ref,
            'line_ids': [
                (0, 0, {
                    'partner_id': partner.id,
                    'account_id': payable_acc.id,
                    'name': entry_ref,
                    'debit': 0.0 if inc else amt,
                    'credit': amt if inc else 0.0,
                }),
                (0, 0, {
                    'partner_id': partner.id,
                    'account_id': counterpart.id,
                    'name': entry_ref,
                    'debit': amt if inc else 0.0,
                    'credit': 0.0 if inc else amt,
                }),
            ],
        })
        move.action_post()

        # If owes less, reconcile against open payable bills
        if direction == 'decrease':
            open_lines = self.env['account.move.line'].sudo().search([
                ('partner_id', '=', partner.id),
                ('account_id', '=', payable_acc.id),
                ('parent_state', '=', 'posted'),
                ('reconciled', '=', False),
                ('company_id', '=', company.id),
            ], order='date asc, id asc')
            if len(open_lines) >= 2 and any(l.debit > 0 for l in open_lines) and any(l.credit > 0 for l in open_lines):
                try:
                    open_lines.reconcile()
                except Exception:
                    pass

        self.env.flush_all()

        new_balance = round(previous_balance + (amt if inc else -amt), 2)

        return {
            'move_id': move.id,
            'move_name': move.name,
            'partner_id': partner.id,
            'partner_name': partner.name,
            'direction': direction,
            'direction_label': _("Owes More") if inc else _("Owes Less"),
            'amount': amt,
            'amount_formatted': currency.format(amt),
            'previous_balance': previous_balance,
            'previous_balance_formatted': currency.format(previous_balance),
            'new_balance': new_balance,
            'new_balance_formatted': currency.format(new_balance),
            'reason': reason_text,
            'date': str(adj_date),
            'cashier_name': cashier_name,
        }

    @api.model
    def _pos_retail_get_misc_journal(self, company):
        """Prefer a dedicated Miscellaneous/General journal over Point of Sale."""
        Journal = self.env['account.journal'].sudo()
        base = [('type', '=', 'general'), ('company_id', '=', company.id)]
        match = (Journal.search(base + [('code', '=', 'MISC')], limit=1)
                 or Journal.search(base + [('name', 'ilike', 'miscellaneous')], limit=1)
                 or Journal.search(base + [('name', 'not ilike', 'point of sale')], limit=1)
                 or Journal.search(base, limit=1))
        if not match:
            match = Journal.search([('type', '=', 'general')], limit=1)
        return match
