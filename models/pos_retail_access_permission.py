from odoo import _, api, fields, models
from odoo.exceptions import UserError
from odoo.addons.base.models.ir_model import MODULE_UNINSTALL_FLAG


def fill_access_names(env, owner_name, vals):
    """Fill the required ir.model.access `name` on nested (0, 0, {...})
    commands in `vals['model_access']` BEFORE the parent create()/write()
    runs. The NOT NULL check fires while Odoo is still flushing the nested
    commands during super().create() itself; patching afterwards is too late.
    Shared by pos.retail.access.permission and pos.retail.access.role.
    Only (0, 0, {...}) "create a line" commands carry a vals dict to patch;
    (1, id, {...}) updates and (4, id) links are left untouched.
    """
    for command in vals.get('model_access') or []:
        if command[0] != 0 or not isinstance(command[2], dict) or command[2].get('name'):
            continue
        model_id = command[2].get('model_id')
        model_name = env['ir.model'].browse(model_id).model if model_id else '?'
        command[2]['name'] = "%s: %s" % (owner_name, model_name)


class PosRetailAccessPermission(models.Model):
    """One entry in the predefined permission catalog.

    A permission IS a real `res.groups` record under the hood (same
    delegation pattern as pos.retail.access.role), so everything it grants
    runs through Odoo's native security engine. A role "has" a permission by
    making its own group imply the permission's group (implied_ids) -- and
    since Odoo 19 resolves implication dynamically at read time, ticking or
    un-ticking a permission on a role grants/revokes for every member
    instantly, with no sync jobs and no residue.

    A permission grants through any combination of:
    * its own ir.model.access rows (`model_access`, delegated) -- used for
      this addon's custom models and read-only slices of core POS models;
    * `implied_ids` (delegated) pointing at ONE minimal native group -- used
      for whole-area grants like "Use Point of Sale" -> group_pos_user;
    * the two grants_* flags -- no ACL at all, read by the price/cost write
      guards in product_template.py / product_product.py.
    """
    _name = 'pos.retail.access.permission'
    _inherits = {'res.groups': 'group_id'}
    _description = "POS Retail Access Permission"
    _order = 'sequence, id'

    group_id = fields.Many2one(
        'res.groups', string="Group", required=True, ondelete='restrict', index=True,
    )
    sequence = fields.Integer(default=10)
    category = fields.Selection(
        [
            ('products', "Products"),
            ('partners', "Customers & Vendors"),
            ('pos', "Point of Sale"),
            ('sales', "Sales"),
            ('purchases', "Purchases"),
            ('inventory', "Inventory"),
            ('accounting', "Invoicing"),
            ('expenses', "Store Expenses"),
            ('reporting', "Reporting"),
            ('configuration', "Configuration"),
        ],
        required=True, default='products', index=True,
    )
    description = fields.Text(
        help="Admin-facing explanation of exactly what this permission unlocks.",
    )
    grants_price_edit = fields.Boolean(
        string="Grants: Edit Sales Price on Existing Products", default=False,
        help="Pure flag, no access rows: a role holding this permission lifts "
             "the Sales Price lock on already-saved products for its members.",
    )
    grants_cost_edit = fields.Boolean(
        string="Grants: Edit Cost on Existing Products", default=False,
        help="Same as above, for the Cost field.",
    )
    role_ids = fields.Many2many(
        'pos.retail.access.role', 'pos_retail_role_permission_rel',
        'permission_id', 'role_id', string="Used by Roles", readonly=True,
    )

    _group_uniq = models.Constraint(
        'unique(group_id)',
        "Each permission must be backed by its own dedicated group.",
    )

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            fill_access_names(self.env, vals.get('name') or _('New Permission'), vals)
        permissions = super().create(vals_list)
        self.env.registry.clear_cache()
        return permissions

    def write(self, vals):
        if 'model_access' in vals and len(self) == 1:
            fill_access_names(self.env, self.name, vals)
        res = super().write(vals)
        # grants_* flag changes touch no res.groups record at all, so none of
        # core's cache clearing fires -- this is the ONE invalidation of the
        # price-lock ormcache (res_users) that only we can perform.
        if set(vals) & {'grants_price_edit', 'grants_cost_edit', 'model_access',
                        'implied_ids', 'user_ids'}:
            self.env.registry.clear_cache()
        return res

    def unlink(self):
        # res_groups_implied_rel is ON DELETE CASCADE: deleting a permission's
        # group would silently strip it from every role's implied_ids with no
        # warning. Force the admin to detach it from roles first -- except
        # during module uninstall, where everything goes anyway.
        if not self.env.context.get(MODULE_UNINSTALL_FLAG):
            still_used = self.filtered('role_ids')
            if still_used:
                raise UserError(_(
                    "Permission(s) %(names)s are still assigned to roles "
                    "(%(roles)s). Remove them from those roles first.",
                    names=", ".join(still_used.mapped('name')),
                    roles=", ".join(still_used.role_ids.mapped('name')),
                ))
        # Same ordering constraint as the role model: ir.model.access.group_id
        # is ondelete='restrict', and _inherits does not cascade in either
        # direction -- clear the access rows, drop this row, then explicitly
        # drop the now-unreferenced group.
        groups = self.group_id
        groups.model_access.unlink()
        res = super().unlink()
        groups.unlink()
        self.env.registry.clear_cache()
        return res
