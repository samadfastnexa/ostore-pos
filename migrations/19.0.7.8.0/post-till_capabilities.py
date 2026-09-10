"""Point the shipped permissions at the till buttons they unlock.

Needed as a migration, not only as a post-init hook, because post_init_hook
runs on INSTALL and never on upgrade. Without this, an existing shop pulling
this version would find the Khata Payment button and the Admin Panel entry
gone from every till: the field that now decides which permission unlocks
them would be empty on records created before the field existed.

The catalogue data file is noupdate, deliberately, so a shop's own edits to
it survive upgrades. That is the same property that stops a new field's
default reaching those records, which is why this exists.

Only fills a capability that is still EMPTY, so a shop that has already
moved a button onto a permission of their own keeps that arrangement. This
never overrules a decision somebody made on purpose.
"""

DEFAULTS = {
    'pos_retail.perm_khata_adjust': '_can_khata',
    'pos_retail.perm_pos_admin': '_can_admin_panel',
    'pos_retail.perm_products_create': '_can_create_product',
}


def migrate(cr, version):
    if not version:
        return

    from odoo import api, SUPERUSER_ID

    env = api.Environment(cr, SUPERUSER_ID, {})
    for xmlid, capability in DEFAULTS.items():
        permission = env.ref(xmlid, raise_if_not_found=False)
        if permission and not permission.till_capability:
            permission.till_capability = capability
