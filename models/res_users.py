from odoo import api, models, tools
from odoo.exceptions import AccessError
from odoo.tools.translate import _


class ResUsers(models.Model):
    _inherit = 'res.users'

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
