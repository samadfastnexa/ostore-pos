"""Keep each contact's khata on the side it belongs to.

The customer ledger reads receivable accounts and the vendor ledger reads
payable accounts, and the two never share a row -- but nothing stopped the
ENTRY being made on the wrong side. Every contact's form offered "Adjust Khata
/ Edit Ledger" and "Receive Payment", both customer-side, and a vendor's form
had no way to pay him at all. So a supplier's paper balance went in as "owes
more" and the money paid to him as "payment received": he turned up in the
Customer Khata list as owing the shop, with the cash recorded coming IN. And
because Odoo raises a contact's customer rank whenever a receivable entry is
posted for him, one wrong entry made the supplier a customer from then on.

This file puts a check in front of every way of writing to either side:

  customer side -- refused for a contact who is a vendor and not a customer
      pos.retail.ledger.adjustment      (Adjust Khata / Edit Ledger)
      pos.retail.khata.payment          (Receive Payment, form and till)
      pos_retail_adjust_customer_khata  (till)
  vendor side -- refused for a contact who is not a vendor
      pos.retail.vendor.ledger.adjustment  (Vendor Khata Adjustment)
      pos.retail.vendor.payment            (Pay Vendor, added here)
      pos_retail_pay_vendor, pos_retail_adjust_vendor_khata  (till)

A contact who genuinely is both -- a builder who buys on credit and also
supplies -- is marked so on purpose with "Also a Customer" / "Also a Vendor"
on the form, and from then on has both ledgers, still kept apart.
"""

from odoo import _, api, fields, models
from odoo.exceptions import UserError

from .res_company import TRADING_COMPANY_DOMAIN


SIDES = {
    'customer': {
        'account_type': 'asset_receivable', 'property': 'property_account_receivable_id',
        'payment_type': 'inbound', 'partner_type': 'customer', 'other': 'vendor',
    },
    'vendor': {
        'account_type': 'liability_payable', 'property': 'property_account_payable_id',
        'payment_type': 'outbound', 'partner_type': 'supplier', 'other': 'customer',
    },
}


# Who holds a ledger right whatever the catalogue says: the accounts core and
# this addon already trust with the books and the till (see
# TILL_SUPERUSER_GROUPS on the permission model). Everybody else needs the
# checkbox ticked on their role -- Roles & Permissions > Customer & Vendor
# Ledgers.
ALWAYS_ALLOWED = ('base.group_system', 'account.group_account_invoice', 'point_of_sale.group_pos_manager')
LEDGER_ACTIONS = {
    'create': "add entries to",
    'edit': "edit entries in",
    'delete': "cancel or move entries in",
}


def ledger_groups(side, action):
    """xmlids of every group that may `action` on `side`'s ledger."""
    groups = ALWAYS_ALLOWED + (f'pos_retail.perm_{side}_ledger_{action}_res_groups',)
    if side == 'vendor':
        groups += ('purchase.group_purchase_manager',)
    elif action == 'create':
        # "Adjust Customer Khata" predates the ledger checkboxes and granted
        # exactly this; nobody who had it loses it.
        groups += ('pos_retail.perm_khata_adjust_res_groups',)
    return groups


def may_enter(env, side, action='create'):
    if env.su:
        return True
    held = env.user.sudo().all_group_ids
    return any((group := env.ref(xmlid, raise_if_not_found=False)) and group in held
               for xmlid in ledger_groups(side, action))


def check_may_enter(env, side, action='create'):
    """Who may write to a khata. The entries are posted with sudo -- a shop
    manager has no rights on journal entries, and should not need them to
    correct a balance -- so the permission is checked here instead."""
    if may_enter(env, side, action):
        return
    raise UserError(_(
        "You are not allowed to %(action)s the %(side)s ledger.\n\n"
        "Ask the owner to tick it on your role: Configuration > Roles & Permissions > "
        "Customer & Vendor Ledgers.",
        action=LEDGER_ACTIONS[action], side=_("vendor") if side == 'vendor' else _("customer")))


class PosRetailAccessPermission(models.Model):
    _inherit = 'pos.retail.access.permission'

    category = fields.Selection(
        selection_add=[('ledgers', "Customer & Vendor Ledgers")],
        ondelete={'ledgers': 'set default'})

    @api.model
    def _pos_retail_file_ledger_permissions(self):
        """Gather the khata permissions under one heading, and give the Admin
        role the new ones once.

        The data files are noupdate, so the three permissions that existed
        before -- the two "View ... Ledger" in Reporting and "Adjust Customer
        Khata" in Invoicing -- would stay where they were, away from the
        Create / Edit / Delete boxes added beside them. Moved only while they
        still sit in their original category, so a shop that re-filed one
        keeps its choice. The Admin role is the one role meant to hold
        everything; it is topped up a single time, so a box the owner later
        unticks stays unticked.
        """
        moves = {'perm_customer_ledger_view': ('reporting', 10), 'perm_vendor_ledger_view': ('reporting', 50),
                 'perm_khata_adjust': ('accounting', 15)}
        for xmlid, (was, sequence) in moves.items():
            permission = self.env.ref(f'pos_retail.{xmlid}', raise_if_not_found=False)
            if permission and permission.category == was:
                permission.write({'category': 'ledgers', 'sequence': sequence})
        Config = self.env['ir.config_parameter'].sudo()
        if Config.get_param('pos_retail.ledger_crud_permissions_seeded'):
            return True
        admin = self.env.ref('pos_retail.access_role_admin', raise_if_not_found=False)
        new = self.browse()
        for side in ('customer', 'vendor'):
            for action in LEDGER_ACTIONS:
                new |= self.env.ref(f'pos_retail.perm_{side}_ledger_{action}', raise_if_not_found=False) or self.browse()
        for xmlid in ('perm_promotions_create', 'perm_promotions_edit', 'perm_promotions_delete',
                      'perm_config_lists_view'):
            new |= self.env.ref(f'pos_retail.{xmlid}', raise_if_not_found=False) or self.browse()
        if admin and new:
            admin.sudo().write({'permission_ids': [(4, permission.id) for permission in new]})
        Config.set_param('pos_retail.ledger_crud_permissions_seeded', '1')
        return True


class ResPartner(models.Model):
    _inherit = 'res.partner'

    def _pos_retail_check_customer_side(self):
        """Refuse a customer-khata entry on a vendor who is not also a customer."""
        for partner in self.sudo():
            if partner.supplier_rank and not partner.customer_rank:
                raise UserError(_(
                    "%(name)s is a VENDOR, not a customer.\n\n"
                    "This would be written to the customer khata, and the vendor would "
                    "show in the Customer Ledger as owing the shop money.\n\n"
                    "To record what the shop owes this vendor use \"Vendor Khata "
                    "Adjustment\"; to record money paid to them use \"Pay Vendor\".\n\n"
                    "If this vendor also buys from the shop on credit, press \"Also a "
                    "Customer\" on their contact form first.",
                    name=partner.display_name,
                ))

    def _pos_retail_check_vendor_side(self):
        """Refuse a vendor-khata entry on a contact who is not a vendor."""
        for partner in self.sudo():
            if not partner.supplier_rank:
                raise UserError(_(
                    "%(name)s is not a vendor.\n\n"
                    "This would be written to the vendor khata, and the contact would "
                    "show in the Vendor Ledger as someone the shop owes money.\n\n"
                    "For a customer use \"Adjust Khata / Edit Ledger\" and \"Receive "
                    "Payment\".\n\n"
                    "If the shop also buys from this contact, press \"Also a Vendor\" on "
                    "their contact form first.",
                    name=partner.display_name,
                ))

    # -- the till ---------------------------------------------------------

    @api.model
    def pos_retail_adjust_customer_khata(self, partner_id, *args, **kwargs):
        self.browse(int(partner_id)).exists()._pos_retail_check_customer_side()
        return super().pos_retail_adjust_customer_khata(partner_id, *args, **kwargs)

    @api.model
    def pos_retail_pay_vendor(self, partner_id, *args, **kwargs):
        self.browse(int(partner_id)).exists()._pos_retail_check_vendor_side()
        return super().pos_retail_pay_vendor(partner_id, *args, **kwargs)

    @api.model
    def pos_retail_adjust_vendor_khata(self, partner_id, *args, **kwargs):
        self.browse(int(partner_id)).exists()._pos_retail_check_vendor_side()
        return super().pos_retail_adjust_vendor_khata(partner_id, *args, **kwargs)

    # -- the contact form -------------------------------------------------

    def action_pos_retail_also_customer(self):
        """A vendor who buys from the shop too: give them a customer khata."""
        self.sudo().filtered(lambda p: not p.customer_rank).write({'customer_rank': 1})
        return True

    def action_pos_retail_also_vendor(self):
        """A customer the shop buys from too: give them a vendor khata."""
        self.sudo().filtered(lambda p: not p.supplier_rank).write({'supplier_rank': 1})
        return True

    def action_open_vendor_payment(self):
        """Pay this vendor: money out of the till or the bank, off what is owed."""
        self.ensure_one()
        self._pos_retail_check_vendor_side()
        return {
            'type': 'ir.actions.act_window',
            'name': _("Pay Vendor"),
            'res_model': 'pos.retail.vendor.payment',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_partner_id': self.id},
        }

    def action_view_vendor_ledger(self):
        """This vendor's bills, payments and adjustments, oldest first."""
        self.ensure_one()
        action = self.env['ir.actions.act_window']._for_xml_id('pos_retail.action_pos_retail_vendor_ledger')
        action['domain'] = [('partner_id', '=', self.id)]
        action['display_name'] = _("Vendor Ledger: %s", self.display_name)
        return action

    def action_print_vendor_statement(self):
        self.ensure_one()
        return self.env.ref('pos_retail.action_report_vendor_statement').report_action(self)


CUSTOMER_SIDE_DOMAIN = "['|', ('supplier_rank', '=', 0), ('customer_rank', '>', 0)]"


class PosRetailLedgerAdjustment(models.TransientModel):
    _inherit = 'pos.retail.ledger.adjustment'

    partner_id = fields.Many2one(domain=CUSTOMER_SIDE_DOMAIN)

    def action_confirm(self):
        self.partner_id._pos_retail_check_customer_side()
        check_may_enter(self.env, 'customer', 'create')
        # The button is offered to shop managers, who cannot post a journal
        # entry themselves; it used to end in an access error for them.
        return super(PosRetailLedgerAdjustment, self.sudo()).action_confirm()


class PosRetailKhataPayment(models.TransientModel):
    _inherit = 'pos.retail.khata.payment'

    partner_id = fields.Many2one(domain=CUSTOMER_SIDE_DOMAIN)

    def _action_confirm_payment(self):
        # The one funnel for the form's Confirm and the till's Receive Payment.
        self.partner_id._pos_retail_check_customer_side()
        return super()._action_confirm_payment()


class PosRetailVendorLedgerAdjustment(models.TransientModel):
    _inherit = 'pos.retail.vendor.ledger.adjustment'

    def action_confirm(self):
        self.partner_id._pos_retail_check_vendor_side()
        check_may_enter(self.env, 'vendor', 'create')
        return super(PosRetailVendorLedgerAdjustment, self.sudo()).action_confirm()


class PosRetailVendorPayment(models.TransientModel):
    """Pay a vendor from the back office.

    The vendor-side twin of pos.retail.khata.payment. Until this existed the
    only payment button on a vendor's form was the customer's "Receive
    Payment", which is how money paid OUT to suppliers came to be recorded as
    money received from them.
    """
    _name = 'pos.retail.vendor.payment'
    _description = "Pay Vendor"

    partner_id = fields.Many2one(
        'res.partner', string="Vendor", required=True,
        domain="[('supplier_rank', '>', 0)]",
        default=lambda self: self.env.context.get('default_partner_id'),
        help="The supplier being paid. The payment comes off what the shop owes them.",
    )
    company_id = fields.Many2one(
        'res.company', string="Branch", domain=TRADING_COMPANY_DOMAIN,
        compute='_compute_company_id', store=True, readonly=False, precompute=True,
        help="Branch paying the money.",
    )
    currency_id = fields.Many2one(
        'res.currency', compute='_compute_company_id', store=True, readonly=False, precompute=True)
    amount_owed = fields.Monetary(
        string="Shop Currently Owes", compute='_compute_amount_owed', currency_field='currency_id',
        help="What the shop owes this vendor right now in this branch: bills and "
             "khata adjustments, less what has already been paid.",
    )
    amount = fields.Monetary(
        string="Amount Paid", required=True, currency_field='currency_id',
        help="How much is being handed to the vendor.",
    )
    journal_id = fields.Many2one(
        'account.journal', string="Paid From", required=True,
        compute='_compute_journal_id', store=True, readonly=False, precompute=True,
        domain="[('type', 'in', ('cash', 'bank')), ('company_id', '=', company_id)]",
        help="Cash if the money came out of the drawer, or the bank account it was sent from.",
    )
    date = fields.Date(required=True, default=fields.Date.context_today)
    memo = fields.Char(string="Note", help="Optional. Shown on the vendor's ledger line.")

    @api.depends('partner_id')
    def _compute_company_id(self):
        for wizard in self:
            company = wizard.partner_id.company_id or self.env.company
            wizard.company_id = company
            wizard.currency_id = company.currency_id

    @api.depends('partner_id', 'company_id')
    def _compute_amount_owed(self):
        Line = self.env['account.move.line'].sudo()
        for wizard in self:
            owed = 0.0
            if wizard.partner_id:
                grouped = Line._read_group(
                    [('partner_id', '=', wizard.partner_id.id),
                     ('account_id.account_type', '=', 'liability_payable'),
                     ('parent_state', '=', 'posted'),
                     ('company_id', '=', (wizard.company_id or self.env.company).id)],
                    aggregates=('debit:sum', 'credit:sum'))
                debit, credit = grouped[0] if grouped else (0.0, 0.0)
                owed = (credit or 0.0) - (debit or 0.0)
            wizard.amount_owed = owed

    @api.depends('company_id')
    def _compute_journal_id(self):
        Journal = self.env['account.journal'].sudo()
        for wizard in self:
            base = [('company_id', '=', (wizard.company_id or self.env.company).id)]
            wizard.journal_id = (Journal.search(base + [('type', '=', 'cash')], limit=1)
                                 or Journal.search(base + [('type', '=', 'bank')], limit=1))

    def action_confirm(self):
        self.ensure_one()
        partner = self.partner_id
        partner._pos_retail_check_vendor_side()
        check_may_enter(self.env, 'vendor', 'create')
        if self.amount <= 0:
            raise UserError(_("Enter how much was paid to the vendor."))
        payable = partner.property_account_payable_id
        if not payable:
            raise UserError(_("%(vendor)s has no payable account set.", vendor=partner.display_name))
        journal = self.journal_id.sudo()
        company = journal.company_id or self.company_id or self.env.company
        payment = self.env['account.payment'].sudo().with_company(company).create({
            'payment_type': 'outbound',
            'partner_type': 'supplier',
            'partner_id': partner.id,
            'amount': self.amount,
            'currency_id': self.currency_id.id,
            'journal_id': journal.id,
            'date': self.date,
            'memo': self.memo or _("Vendor payment"),
            'company_id': company.id,
        })
        payment.action_post()
        # Oldest bills first, the same order the till's Pay Vendor settles in.
        open_lines = self.env['account.move.line'].sudo().search([
            ('partner_id', '=', partner.id),
            ('account_id.account_type', '=', 'liability_payable'),
            ('parent_state', '=', 'posted'),
            ('reconciled', '=', False),
            ('company_id', '=', company.id),
        ], order='date asc, id asc')
        for account in open_lines.account_id:
            lines = open_lines.filtered(lambda l: l.account_id == account)
            if any(l.debit > 0 for l in lines) and any(l.credit > 0 for l in lines):
                try:
                    with self.env.cr.savepoint():
                        lines.reconcile()
                except UserError:
                    pass  # the payment stands; matching it to bills can be done by hand
        return partner.action_view_vendor_ledger()
