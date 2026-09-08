"""Point every part of a till at its OWN company's records, creating the
journal it is missing if that is what is wrong.

    venv/Scripts/python.exe odoo/odoo-bin shell -c odoo.conf -d <db> --no-http \
        < custom_addons/pos_retail/scripts/fix_register_wiring.py

On the server:
    sudo -u odoo /opt/odoo/venv/bin/python3 /opt/odoo/odoo/odoo-bin shell \
        -c /etc/odoo/odoo.conf -d ostore_live --no-http \
        < /opt/odoo/custom_addons/pos_retail/scripts/fix_register_wiring.py

This repairs what check_branch_setup.py reports as "every register is wired
inside its own company". A branch register invoicing through the PARENT's
sales journal books its sales into the wrong company's accounts, which is
cheap to correct now and expensive to unpick after a month of trading.

The usual cause is not a mistake in the register: it is that the branch was
never given a sales journal of its own, so the only one on offer belonged to
the parent. Where that is the case this creates one, mirroring the shape a
correctly commissioned branch already has (its own Sales journal, its own
cash journal), and then repoints the register at it.

READ ONLY until you say otherwise. It prints exactly what it would change and
stops. Set APPLY = True below to carry those changes out -- deliberately a
separate step, because this is accounting configuration on a live database.

What it does NOT do: move entries that have already been posted. Invoices
already booked into the parent's journal stay where they are. This changes
where the NEXT one goes. If existing entries need moving, that is an
accountant's decision, not a script's.
"""

APPLY = False

Config = env['pos.config'].sudo()
Journal = env['account.journal'].sudo()

# Fields where a cross-company value can be repaired by pointing at the
# equivalent record in the register's own company. Everything else is
# reported and left alone, because the right answer is not obvious.
JOURNAL_FIELDS = ('journal_id', 'invoice_journal_id')

planned, manual, fine = [], [], []


def free_code(company, preferred):
    # active_test=False deliberately: account_journal_code_company_uniq is a
    # database constraint on (company_id, code) and does not care whether a
    # journal is archived. Searching without it picks a code that looks free,
    # and the INSERT then fails on a journal nobody can even see.
    archived_too = Journal.with_context(active_test=False)
    base = (preferred or 'INV')[:5]
    code = base
    n = 1
    while archived_too.search_count([('company_id', '=', company.id), ('code', '=', code)]):
        n += 1
        code = '%s%s' % (base[:4], n)
    return code


def own_journal(company, like):
    """The company's own journal of the same type, created if it has none.

    Only ACTIVE journals count as usable: an archived one is archived for a
    reason and should not be silently wired back onto a live register.
    """
    existing = Journal.search([
        ('company_id', '=', company.id), ('type', '=', like.type)], limit=1)
    if existing:
        return existing, False

    archived = Journal.with_context(active_test=False).search([
        ('company_id', '=', company.id), ('type', '=', like.type),
        ('active', '=', False)], limit=1)
    if archived:
        print("      NOTE     : %s has an ARCHIVED %r journal (%r). A new one is"
              % (company.name, like.type, archived.name))
        print("                 made rather than reviving it -- unarchive it instead")
        print("                 if that is the one you meant to use.")
    if not APPLY:
        return None, True
    created = Journal.create({
        'name': like.name,
        'type': like.type,
        'code': free_code(company, like.code),
        'company_id': company.id,
    })
    return created, True


for config in Config.with_context(active_test=False).search([]):
    company = config.company_id
    for fname, field in config._fields.items():
        if field.type != 'many2one' or not field.store or fname in ('create_uid', 'write_uid'):
            continue
        value = config[fname]
        if not value or 'company_id' not in value._fields:
            continue
        if not value.company_id or value.company_id == company:
            continue

        if fname in JOURNAL_FIELDS:
            planned.append((config, fname, value, company))
        else:
            manual.append((config.name, fname, value.display_name,
                           value.company_id.name, company.name))

print()
print("=" * 78)
print("REGISTER WIRING" + ("" if APPLY else "   (DRY RUN -- nothing written)"))
print("=" * 78)

if not planned and not manual:
    print("  every register already points only at its own company's records")

for config, fname, value, company in planned:
    journal, created_now = own_journal(company, value)
    print("  %s.%s" % (config.name, fname))
    print("      now      : %r  owned by %s" % (value.name, value.company_id.name))
    if journal:
        print("      becomes  : %r  owned by %s%s" % (
            journal.name, journal.company_id.name,
            "   (created just now)" if created_now else ""))
        if APPLY:
            config.write({fname: journal.id})
            if created_now and not journal.default_account_id:
                print("      NOTE     : the new journal has no default account. Set one on")
                print("                 the journal before invoicing, or posting will fail.")
    else:
        print("      becomes  : a new %r journal for %s, which this run will not"
              % (value.type, company.name))
        print("                 create because APPLY is False")

if manual:
    print()
    print("  Left for a person to decide (not a journal, so there is no obvious")
    print("  equivalent to swap in):")
    for name, fname, disp, owner, should_be in manual:
        print("      %s.%s -> %r owned by %s, but the register belongs to %s"
              % (name, fname, disp, owner, should_be))

if APPLY:
    env.cr.commit()
    print()
    print("Written. Re-run check_branch_setup.py to confirm.")
else:
    print()
    print("=" * 78)
    print("Nothing was written. To carry the changes above out, edit this file and")
    print("set APPLY = True near the top, then run it again.")
    print("=" * 78)
