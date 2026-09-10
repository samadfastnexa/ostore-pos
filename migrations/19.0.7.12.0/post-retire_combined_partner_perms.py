"""Retire the combined Customers & Vendors permissions.

They were superseded by eight split ones, and leaving both in the catalogue
was the shop's objection: two entries meaning nearly the same thing is how a
role ends up granting something nobody intended.

They cannot simply be deleted. Roles already hold them, and the permission
model refuses to unlink one that a role still uses -- for good reason: the
implied-groups table cascades on delete, so removing a permission's group
would silently strip it from every role with no warning at all.

So each role is moved onto the split equivalents FIRST, and only then are
the old entries removed. Nobody loses access: a role that could create
contacts of either kind ends up holding both create permissions.

"Manage Customers & Vendors" is deliberately kept and renamed rather than
retired. It is not a duplicate of the split entries: it hands over Odoo's
own contact-manager group, which is a real and separate grant, and the
sidebar menus name its group. Renaming it to "Manage All Contacts" removes
the overlap in wording without removing the grant.
"""

# old xmlid -> the split permissions a role holding it should end up with
REPLACEMENTS = {
    'pos_retail.perm_partners_create': (
        'pos_retail.perm_customers_create', 'pos_retail.perm_vendors_create'),
    'pos_retail.perm_partners_edit': (
        'pos_retail.perm_customers_edit', 'pos_retail.perm_vendors_edit'),
    'pos_retail.perm_partners_delete': (
        'pos_retail.perm_customers_delete', 'pos_retail.perm_vendors_delete'),
}


def migrate(cr, version):
    if not version:
        return

    from odoo import api, SUPERUSER_ID

    env = api.Environment(cr, SUPERUSER_ID, {})

    manage = env.ref('pos_retail.perm_partners_manage', raise_if_not_found=False)
    if manage and manage.name == "Manage Customers & Vendors":
        manage.name = "Manage All Contacts"

    doomed = env['pos.retail.access.permission']
    for old_xmlid, new_xmlids in REPLACEMENTS.items():
        old = env.ref(old_xmlid, raise_if_not_found=False)
        if not old:
            continue
        replacements = [
            env.ref(x, raise_if_not_found=False) for x in new_xmlids
        ]
        replacements = [r for r in replacements if r]
        if len(replacements) != len(new_xmlids):
            # A replacement is missing, so moving the roles would quietly
            # narrow what they grant. Left alone and reported rather than
            # half-done.
            continue
        for role in old.role_ids:
            role.permission_ids = [(4, r.id) for r in replacements] + [(3, old.id)]
        doomed |= old

    if doomed:
        # role_ids is recomputed from the writes above; re-read before the
        # unlink guard checks it, or it refuses on a link that is already gone.
        doomed.invalidate_recordset(['role_ids'])
        doomed.unlink()
