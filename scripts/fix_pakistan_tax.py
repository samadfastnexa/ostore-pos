"""Stop Pakistani customers being zero-rated as exports.

    venv/Scripts/python.exe odoo/odoo-bin shell -c odoo.conf -d <db> --no-http \
        < custom_addons/pos_retail/scripts/fix_pakistan_tax.py

On the server:
    sudo -u odoo /opt/odoo/venv/bin/python3 /opt/odoo/odoo/odoo-bin shell \
        -c /etc/odoo/odoo.conf -d ostore_live --no-http \
        < /opt/odoo/custom_addons/pos_retail/scripts/fix_pakistan_tax.py

THE FAULT. Every company has country Pakistan and currency PKR, but its
FISCAL country -- the one Odoo actually uses for tax -- is United States,
left behind by the generic chart of accounts. So a customer in Karachi is
foreign, the auto-applying "Foreign Trade" position catches them, and their
tax is mapped to "0% Exports". The products are innocent: 910 of 911 carry a
sales tax. It is being mapped away at the moment of sale.

WHAT THIS CHANGES.

  1. Fiscal country -> Pakistan, on every company. This is the root of it.
  2. The "Domestic" position, which points at the United States, is pointed
     at Pakistan instead, so a Pakistani customer matches it.
  3. "Foreign Trade" stops applying to everyone. It keeps working for a
     genuine export, which is what it is for.

WHAT THIS DOES NOT CHANGE, deliberately: the rate on any product. The shop
asked for tax to be dynamic -- set per product, and whatever is set is what
is charged -- so nothing here overrides a product's own tax. It only stops
that tax being replaced by zero.

It does add the Pakistani rates to CHOOSE from (18% standard, 17% previous,
and an exempt 0%) where they are missing, so a product can be moved onto the
right one without anyone hand-building a tax record.

READ ONLY until APPLY is set to True. Nothing is written before that, and
the report shows what a real customer gets both before and after.
"""

APPLY = False

Company = env['res.company'].sudo()
FP = env['account.fiscal.position'].sudo()
Tax = env['account.tax'].sudo()
Partner = env['res.partner'].sudo()

pakistan = env.ref('base.pk')

# name -> (percent, type). Kept deliberately small: these are the rates a
# hardware shop actually meets. More can be added in Accounting if needed.
WANTED_TAXES = [
    ("GST 18%", 18.0),
    ("GST 17%", 17.0),
    ("Exempt 0%", 0.0),
]


def sample_customer():
    return (Partner.search([('customer_rank', '>', 0), ('country_id', '=', pakistan.id)], limit=1)
            or Partner.search([('customer_rank', '>', 0)], limit=1))


def report(label):
    print()
    print("  %s" % label)
    customer = sample_customer()
    for company in Company.search([('child_ids', '=', False)]):
        position = FP.with_company(company)._get_fiscal_position(customer)
        mapped = "(no mapping -- the product's own tax is charged)"
        if position and position.tax_map:
            mapped = "MAPS TAX AWAY: %s" % position.tax_map
        print("      %-14r fiscal country=%-14r customer %r -> %r %s" % (
            company.name[:12], company.account_fiscal_country_id.name,
            customer.name[:12], position.name or "none", mapped))


print("=" * 78)
print("PAKISTAN TAX" + ("" if APPLY else "   (DRY RUN -- nothing written)"))
print("=" * 78)
report("BEFORE")

if not APPLY:
    print()
    print("  Would change:")
    for company in Company.search([]):
        if company.account_fiscal_country_id != pakistan:
            print("      %-22r fiscal country %r -> 'Pakistan'"
                  % (company.name, company.account_fiscal_country_id.name))
    for position in FP.search([('is_domestic', '=', True)]):
        if position.country_id != pakistan:
            print("      position %-20r country %r -> 'Pakistan'"
                  % (position.name, position.country_id.name))
    for position in FP.search([('is_domestic', '=', False), ('auto_apply', '=', True),
                               ('country_id', '=', False)]):
        print("      position %-20r stop auto-applying to every country"
              % position.name)
    for company in Company.search([]):
        missing = [n for n, _p in WANTED_TAXES
                   if not Tax.search_count([('name', '=', n), ('company_id', '=', company.id)])]
        if missing:
            print("      %-22r add rates to choose from: %s" % (company.name, ", ".join(missing)))
    print()
    print("=" * 78)
    print("Nothing was written. Set APPLY = True, or pipe it:")
    print("  sed 's/^APPLY = False/APPLY = True/' <this file> | odoo-bin shell ...")
    print("=" * 78)
else:
    for company in Company.search([]):
        company.account_fiscal_country_id = pakistan.id

    for position in FP.search([('is_domestic', '=', True)]):
        position.country_id = pakistan.id

    # An export position that matches every country is what swallowed the
    # domestic sale. Left in place and left mapping, but it must be chosen
    # deliberately for a genuine export rather than catching the counter.
    for position in FP.search([('is_domestic', '=', False), ('auto_apply', '=', True),
                               ('country_id', '=', False)]):
        position.auto_apply = False

    # A tax needs a group, and the existing groups are stamped "United
    # States" like everything else here. Reused rather than replaced -- the
    # group only buckets taxes on reports, and inventing parallel ones would
    # split the same rate across two lines. Their country is corrected too.
    TaxGroup = env['account.tax.group'].sudo()
    TaxGroup.search([]).write({'country_id': pakistan.id})

    def group_for(company, percent):
        name = "Tax %g%%" % percent
        group = TaxGroup.search(
            ['|', ('company_id', '=', company.id), ('company_id', '=', False),
             ('name', '=', name)], limit=1)
        if not group:
            group = TaxGroup.create({
                'name': name, 'company_id': company.id, 'country_id': pakistan.id})
        return group

    # Created on the PARENT only. A branch shares its parent's chart of
    # accounts here, and account_tax._constrains_name treats the company tree
    # as one namespace -- so making "GST 18%" on each branch collides with the
    # parent's. One tax, usable from every till, which is also how the taxes
    # already on 910 products are set up.
    roots = Company.search([('parent_id', '=', False)]) or Company.search([])
    for company in roots:
        for name, percent in WANTED_TAXES:
            for use in ('sale', 'purchase'):
                # Odoo enforces one tax NAME per company, whatever it is used
                # for, so a sale and a purchase tax cannot share one. The
                # purchase side is suffixed rather than skipped: a shop that
                # charges GST also reclaims it, and it needs both sides.
                tax_name = name if use == 'sale' else "%s (Purchase)" % name
                exists = Tax.search_count([
                    ('name', '=', tax_name), ('company_id', '=', company.id)])
                if not exists:
                    Tax.create({
                        'name': tax_name, 'amount': percent, 'amount_type': 'percent',
                        'type_tax_use': use, 'company_id': company.id,
                        'country_id': pakistan.id,
                        'tax_group_id': group_for(company, percent).id,
                    })

    env.cr.commit()
    report("AFTER")
    print()
    print("  Rates now available to put on a product:")
    for company in Company.search([('child_ids', '=', False)]):
        # Include the parent's taxes: a branch shares them, and listing only
        # its own made it look like the new rates had not arrived.
        tree = [company.id] + company.parent_ids.ids
        names = Tax.search([('company_id', 'in', tree),
                            ('type_tax_use', '=', 'sale')]).mapped('name')
        print("      %-14r %s" % (company.name[:12], ", ".join(sorted(set(names)))))
    print()
    print("  Products keep the tax they already carry. Change a product's tax on")
    print("  its own form (Sales tab), or in bulk from the product list.")
