from odoo import models, tools
from odoo.exceptions import AccessError
from odoo.tools.translate import _


class ResUsers(models.Model):
    _inherit = 'res.users'

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
