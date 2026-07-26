from odoo import _, api, fields, models


class PosRetailAccessRole(models.Model):
    """A super-admin-facing "role" a user can be assigned.

    Named distinctly from the pre-existing `pos.retail.discount.role` (cashier
    discount limits) -- that one is business-logic data read only by our own
    JS, with no server-side enforcement at all. This model is deliberately
    different: it IS a real `res.groups` record under the hood (delegation
    inheritance), so every permission it grants runs through Odoo's actual ACL
    engine (`ir.model.access`), not a parallel system a determined user could
    bypass via direct RPC.

    `model_access` (which model/group can Create/Edit/Delete) is delegated
    straight from `res.groups` -- shown directly in this model's own form, not
    copied into a second custom line model. A hand-synced copy would be a
    stale-data bug waiting to happen (edit/delete a line, forget to also
    update the real ir.model.access row); exposing the real field means there
    is exactly one place this data lives.

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
    )
    sequence = fields.Integer(default=10)
    active = fields.Boolean(
        default=True,
        help="Archiving a role immediately removes ALL its users from it -- "
             "they lose everything it granted, and are NOT restored if the "
             "role is unarchived later. Re-add them manually if needed.",
    )

    can_edit_product_price = fields.Boolean(
        string="Can Edit Sales Price on Existing Products", default=False,
        help="A user with only this role may still CREATE a product at any "
             "price. This flag controls whether they may also change the "
             "Sales Price on a product that already exists. Off by default: "
             "assigning a role locks price edits unless explicitly granted here.",
    )
    can_edit_product_cost = fields.Boolean(
        string="Can Edit Cost on Existing Products", default=False,
        help="Same as above, for the Cost field.",
    )

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
        # clear_cache() (default namespace), NOT clear_cache('groups'):
        # _pos_retail_can_edit_price_field lives in the default namespace so
        # that core's own membership writes (res.users.write / res.groups.write
        # clear 'stable'/'default' only, never 'groups') invalidate it too.
        self.env.registry.clear_cache()
        return roles

    @api.model
    def _pos_retail_fill_access_names(self, role_name, vals):
        for command in vals.get('model_access') or []:
            # Only (0, 0, {...}) "create a new line" commands carry a vals
            # dict to patch; (1, id, {...}) updates and (4, id) links have
            # nothing here to fill in and are left untouched.
            if command[0] != 0 or not isinstance(command[2], dict) or command[2].get('name'):
                continue
            model_id = command[2].get('model_id')
            model_name = self.env['ir.model'].browse(model_id).model if model_id else '?'
            command[2]['name'] = "%s: %s" % (role_name, model_name)

    def write(self, vals):
        if 'model_access' in vals and len(self) == 1:
            self._pos_retail_fill_access_names(self.name, vals)
        res = super().write(vals)
        if 'active' in vals and not vals['active']:
            # Archiving is the primary way to revoke a role (see unlink() for
            # why hard delete is a secondary action). Clear its members
            # immediately rather than leaving a still-fully-functional group
            # around with no active role record pointing at it -- the group
            # itself is not deleted (nothing else does that automatically;
            # see unlink()), but with zero users it grants nothing.
            self.mapped('group_id').write({'user_ids': [(5, 0, 0)]})
        if set(vals) & {'active', 'can_edit_product_price', 'can_edit_product_cost', 'user_ids'}:
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
