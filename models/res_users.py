from odoo import api, fields, models, tools
from odoo.exceptions import AccessError, UserError
from odoo.tools.translate import _


class ResUsers(models.Model):
    _inherit = 'res.users'

    def _pos_retail_default_company(self):
        """Land a new user in a shop rather than the holding company.

        Core defaults both company fields to self.env.company, so a user
        created while the owner happens to be switched to MURSHID Company is
        put there too -- a company with no till, no shelves and next to no
        products. The new cashier then signs in to an empty screen and nothing
        explains it.

        The parent is still offered in the dropdown on purpose. It holds the
        chart of accounts, the NTN and the taxes, so somebody has to be able to
        work in it; filtering it out would make the legal entity impossible to
        administer. Only the starting point moves.
        """
        company = self.env.company
        if not company.child_ids:
            return company                      # already a shop, or a plain single company
        shops = self.env.user.company_ids.filtered(lambda c: not c.child_ids)
        return shops[0] if shops else company

    company_id = fields.Many2one(
        default=lambda self: self._pos_retail_default_company().id)
    company_ids = fields.Many2many(
        default=lambda self: self._pos_retail_default_company().ids)

    @api.model_create_multi
    def create(self, vals_list):
        """Send new POS managers to the dashboard; leave everyone else alone.

        This replaces an ir.default that set the dashboard as the home action
        for EVERY user created. Combined with the manager-only guard on
        get_dashboard_data, that meant each newly created cashier logged in,
        was thrown at the dashboard, and got "available to Point of Sale
        managers only" over an empty screen -- every time, forever. Deciding
        per user at create time is the fix; a blanket default cannot know
        which groups the user ended up in.
        """
        users = super().create(vals_list)
        dashboard = self.env.ref('pos_retail.action_pos_retail_dashboard',
                                 raise_if_not_found=False)
        if not dashboard:
            return users
        for user in users:
            if user.share or user.action_id:
                continue                      # portal user, or a deliberate choice
            if user.has_group('point_of_sale.group_pos_manager'):
                user.action_id = dashboard.id
        return users

    @api.model
    def _pos_retail_sync_dashboard_home(self):
        """Put the POS dashboard home action on managers, and only managers.

        Done in Python, not as <record>/<function> domains, for two reasons a
        data file cannot handle:

        * "is a POS manager" means the group OR anything implying it, which
          has_group() resolves and a plain domain on group_ids does not. An
          earlier attempt using all_group_ids matched nobody, so the follow-up
          write cleared the real managers instead.
        * The old ir.default has to be DELETED. Dropping the <function> that
          created it leaves the record in place, so every newly created user
          still inherits the dashboard as their landing page and walks into the
          manager-only guard. Removing a default is an action, not an omission.
        """
        dashboard = self.env.ref('pos_retail.action_pos_retail_dashboard',
                                 raise_if_not_found=False)
        if not dashboard:
            return True

        self.env['ir.default'].sudo().discard_values(
            'res.users', 'action_id', [dashboard.id])

        for user in self.sudo().search([('share', '=', False)]):
            is_manager = user.has_group('point_of_sale.group_pos_manager')
            if is_manager and not user.action_id:
                user.action_id = dashboard.id
            elif not is_manager and user.action_id.id == dashboard.id:
                # Would greet them with "managers only" on every login.
                user.action_id = False
        return True

    def _change_password(self, new_passwd):
        if not self.env.user._is_system():
            raise AccessError(_("Only the Super Admin can set or reset a password. Please contact them."))
        super()._change_password(new_passwd)

    def unlink(self):
        """Keep at least one way back into the system.

        Core protects four accounts by xmlid -- __system__, base.user_admin,
        and the portal/public templates -- and nothing else. The account that
        actually administers THIS database was created by hand, so it carries
        no xmlid and core will delete it without a word. Nobody notices until
        the next login, and by then the only account left holding Settings is
        __system__, which has no usable password. That is a locked door with
        the key on the inside.

        Two ways in are shut here: deleting the last administrator, and
        deleting the account you are signed in as. Both are recoverable only
        from a database shell.

        Written as unlink() rather than @api.ondelete deliberately: ondelete
        methods have no guaranteed order between modules, so whichever fires
        first decides the wording. unlink() runs before all of them and the
        message is always this one.
        """
        if self.env.uid in self.ids:
            raise UserError(_(
                "You cannot delete the account you are signed in as. Ask "
                "another administrator to do it after you have signed out, or "
                "hide it instead."))

        admin_group = self.env.ref('base.group_system', raise_if_not_found=False)
        if admin_group:
            doomed_admins = self.filtered(lambda u: admin_group in u.all_group_ids)
            if doomed_admins:
                # SUPERUSER_ID is excluded on purpose: it is Odoo's internal
                # account for updates and module installs, has no password
                # anyone can sign in with, and so is no way back in.
                survivors = self.sudo().with_context(active_test=False).search_count([
                    ('id', 'not in', self.ids + [api.SUPERUSER_ID]),
                    ('all_group_ids', 'in', admin_group.id),
                    ('share', '=', False),
                ])
                if not survivors:
                    raise UserError(_(
                        "%(names)s cannot be deleted, because that would leave "
                        "nobody who can open Settings, add users or set "
                        "passwords. You would be locked out of your own "
                        "system, and only a technician with database access "
                        "could let you back in.\n\n"
                        "Give another user administrator rights first, then "
                        "delete this one. Or just hide it: it stops being able "
                        "to sign in, and its history stays intact.",
                        names=", ".join(doomed_admins.mapped('login')),
                    ))

        return super().unlink()

    @tools.ormcache('self.id', 'fname')
    def _pos_retail_can_edit_price_field(self, fname):
        """Whether this user may change `fname` (list_price/standard_price) on
        a product that already exists.

        A user who belongs to NO pos.retail.access.role at all is always
        allowed -- this feature only restricts users actually assigned one of
        the new roles, so every admin/manager who exists today is unaffected.
        Otherwise: allowed if at least one of their roles explicitly grants it
        (additive, same composition rule as every other Odoo permission).

        Cached in the DEFAULT ormcache namespace on purpose, NOT 'groups':
        the 'groups' container is only ever cleared by an explicit
        clear_cache('groups') (res.groups create/unlink, or implied_ids
        changes) -- assigning/removing a user from a group goes through
        res.users.write / res.groups.write, which clear only the
        'stable'/'default' containers. The default namespace is exactly the
        one core uses for the analogous per-user membership cache
        (res.users._get_group_ids), so membership changes from ANY direction
        invalidate this too. Membership is checked through all_user_ids so a
        role granted via another group's implied_ids chain is honoured the
        same as an explicit assignment.
        """
        self.ensure_one()
        field_map = {
            'list_price': 'can_edit_product_price',
            'standard_price': 'can_edit_product_cost',
        }
        role_field = field_map[fname]
        roles = self.env['pos.retail.access.role'].sudo().search([('all_user_ids', 'in', self.id)])
        if not roles:
            return True
        return any(roles.mapped(role_field))
