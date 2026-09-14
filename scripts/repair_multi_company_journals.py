"""Fix multi-company journal access and ensure proper company hierarchy.

Run on the server:
    sudo -u odoo /opt/odoo/venv/bin/python3 /opt/odoo/odoo/odoo-bin shell \
        -c /etc/odoo/odoo.conf -d ostore_live --no-http \
        < /opt/odoo/custom_addons/pos_retail/scripts/repair_multi_company_journals.py
"""

Company = env['res.company'].sudo()
root = Company.search([('parent_id', '=', False)], order='id', limit=1)
print("Root company:", root.name, f"(id={root.id})")

# 1. Ensure all branch companies have parent_id = root.id
branches = Company.search([('id', '!=', root.id)])
for b in branches:
    if b.parent_id != root:
        print(f"Setting parent_id on branch '{b.name}' (id={b.id}) -> '{root.name}'")
        b.parent_id = root.id

# 2. Ensure Administrator (user id=2) has all companies in company_ids
admin_user = env['res.users'].sudo().browse(2)
if admin_user.exists():
    all_companies = Company.search([])
    admin_user.write({'company_ids': [(6, 0, all_companies.ids)]})
    print(f"Administrator (id=2) allowed companies set to: {all_companies.mapped('name')}")

# 3. Relax account.journal multi-company rule
rule = env.ref('account.journal_comp_rule', raise_if_not_found=False)
if rule:
    desired = "['|', '|', '|', '|', ('company_id', '=', False), ('company_id', 'parent_of', company_ids), ('company_id', 'child_of', company_ids), ('company_id', 'in', company_ids), ('company_id', 'in', user.company_ids.ids)]"
    rule.sudo().write({
        'name': 'Journal: visible to branches and parent',
        'domain_force': desired,
    })
    print("account.journal_comp_rule updated successfully.")

env.cr.commit()
print("All repairs committed successfully.")
