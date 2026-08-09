from odoo import _, api, fields, models
from odoo.fields import Command

from .pos_retail_access_permission import fill_access_names


class PosRetailAccessRole(models.Model):
    """A super-admin-facing "role" a user can be assigned.

    Named distinctly from the pre-existing `pos.retail.discount.role` (cashier
    discount limits) -- that one is business-logic data read only by our own
    JS, with no server-side enforcement at all. This model is deliberately
    different: it IS a real `res.groups` record under the hood (delegation
    inheritance), so every permission it grants runs through Odoo's actual ACL
    engine (`ir.model.access`), not a parallel system a determined user could
    bypass via direct RPC.

    Roles are composed from the PERMISSION CATALOG (`permission_ids` ->
    pos.retail.access.permission): assigning permissions makes this role's
    group imply the permissions' groups, which Odoo 19 resolves dynamically
    everywhere (ACLs, record rules, menus, view gates). The raw `model_access`
    grid (delegated straight from `res.groups`) remains visible read-only in
    debug mode for transparency; it is no longer the editing surface.

    The two `can_edit_product_*` booleans are the one thing `ir.model.access`
    cannot express natively: "settable when creating a product, locked once it
    exists." That asymmetry is enforced by write() guards on product.template
    / product.product (see those files) -- imitating the same pattern Odoo
    core itself uses in account.move.write() for its own posted-move lock.
    """
    _name = 'pos.retail.access.role'
    _inherits = {'res.groups': 'group_id'}
    _description = "POS Retail Access Role"
    _order = 'sequence, id'

    group_id = fields.Many2one(
        'res.groups', string="Group", required=True, ondelete='restrict', index=True,
        help="Technical field: the security group that actually carries this "
             "role's rights. It is created and kept in step with the role "
             "automatically, so there is no reason to change it by hand.",
    )
    sequence = fields.Integer(
        default=10,
        help="Order this role appears in on the list, lowest number first. It "
             "has no effect at all on what the role is allowed to do.",
    )
    active = fields.Boolean(
        default=True,
        help="Archiving a role immediately removes ALL its users from it -- "
             "they lose everything it granted, and are NOT restored if the "
             "role is unarchived later. Re-add them manually if needed.",
    )

    permission_ids = fields.Many2many(
        'pos.retail.access.permission', 'pos_retail_role_permission_rel',
        'role_id', 'permission_id', string="Permissions",
        help="What this role grants. Each permission is backed by a real "
             "group; the role's own group implies the selected permissions' "
             "groups, so granting and revoking take effect immediately for "
             "every member.",
    )
    can_edit_product_price = fields.Boolean(
        string="Can Edit Sales Price on Existing Products",
        compute='_compute_can_edit_flags',
        help="Computed from the assigned permissions (the \"Change Sales "
             "Price on Existing Products\" catalog entry). A user with only "
             "this role may still CREATE a product at any price; this "
             "controls changing the price of one that already exists.",
    )
    can_edit_product_cost = fields.Boolean(
        string="Can Edit Cost on Existing Products",
        compute='_compute_can_edit_flags',
        help="Same as above, for the Cost field.",
    )

    @api.depends('permission_ids.grants_price_edit', 'permission_ids.grants_cost_edit')
    def _compute_can_edit_flags(self):
        for role in self:
            role.can_edit_product_price = any(role.permission_ids.mapped('grants_price_edit'))
            role.can_edit_product_cost = any(role.permission_ids.mapped('grants_cost_edit'))

    def _pos_retail_sync_permission_groups(self):
        """Make the role's group imply EXACTLY the selected permissions'
        groups. Full replace on purpose: permission_ids is the single source
        of truth for this group's implied_ids -- anything hand-added through
        Settings > Technical > Groups is wiped on the next role save. The
        set-compare guard avoids a gratuitous res.groups.write (and its
        registry cache clears) when nothing actually changed. Not sudo():
        res.groups sets _allow_sudo_commands = False, and the only writers
        here are base.group_system users who hold the res.groups ACL anyway.
        """
        for role in self:
            wanted = role.permission_ids.group_id
            if set(role.group_id.implied_ids.ids) != set(wanted.ids):
                role.group_id.implied_ids = [Command.set(wanted.ids)]

    @api.model_create_multi
    def create(self, vals_list):
        # ir.model.access.name is required, and the NOT NULL check fires
        # while Odoo is still flushing the nested model_access commands
        # DURING super().create() -- by the time create() would normally
        # return, it's already too late to patch anything after the fact.
        # The admin-facing form covers this with a view-level context
        # default, but that only helps rows added through that one form; a
        # row created any other way (direct API, import, a future screen)
        # needs the name filled in here, before the parent create runs.
        for vals in vals_list:
            self._pos_retail_fill_access_names(vals.get('name') or _('New Role'), vals)
        roles = super().create(vals_list)
        roles._pos_retail_sync_permission_groups()
        # clear_cache() (default namespace), NOT clear_cache('groups'):
        # _pos_retail_can_edit_price_field lives in the default namespace so
        # that core's own membership writes (res.users.write / res.groups.write
        # clear 'stable'/'default' only, never 'groups') invalidate it too.
        self.env.registry.clear_cache()
        return roles

    @api.model
    def _pos_retail_fill_access_names(self, role_name, vals):
        fill_access_names(self.env, role_name, vals)

    def write(self, vals):
        if 'model_access' in vals and len(self) == 1:
            self._pos_retail_fill_access_names(self.name, vals)
        res = super().write(vals)
        if 'permission_ids' in vals:
            self._pos_retail_sync_permission_groups()
        if 'active' in vals and not vals['active']:
            # Archiving is the primary way to revoke a role (see unlink() for
            # why hard delete is a secondary action). Clear its members
            # immediately rather than leaving a still-fully-functional group
            # around with no active role record pointing at it -- the group
            # itself is not deleted (nothing else does that automatically;
            # see unlink()), but with zero users it grants nothing.
            self.mapped('group_id').write({'user_ids': [(5, 0, 0)]})
        if set(vals) & {'active', 'user_ids', 'permission_ids'}:
            self.env.registry.clear_cache()
        return res

    def unlink(self):
        # ir.model.access.group_id is ondelete='restrict', and _inherits does
        # NOT cascade cleanup in either direction (confirmed against core):
        # deleting this row alone would leave the underlying res.groups record
        # -- and everything it still grants -- silently orphaned, with nothing
        # in this addon pointing at it anymore. Order matters: clear the
        # access rows first (satisfies the restrict FK), delete this row,
        # THEN explicitly delete the now-unreferenced group.
        groups = self.mapped('group_id')
        groups.model_access.unlink()
        res = super().unlink()
        groups.unlink()
        self.env.registry.clear_cache()
        return res
