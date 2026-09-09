"""Confirm a deployment actually landed, and flag what still needs doing.

    venv/Scripts/python.exe odoo/odoo-bin shell -c odoo.conf -d <db> --no-http \
        < custom_addons/pos_retail/scripts/verify_deployment.py

On the server:
    sudo -u odoo /opt/odoo/venv/bin/python3 /opt/odoo/odoo/odoo-bin shell \
        -c /etc/odoo/odoo.conf -d ostore_live --no-http \
        < /opt/odoo/custom_addons/pos_retail/scripts/verify_deployment.py

READ ONLY. Written because "did the pull work" kept being answered by
hunting through screens for a renamed button, and a plain `git pull` does
not rebuild assets -- so code can be on disk while the till still runs the
old JS. Everything here is checked against the DATABASE, which is what the
upgrade actually changes.

Two sections, and the difference matters:

  CODE      what the upgrade should have installed. A failure here means the
            pull or the -u upgrade did not complete; run it again.
  SETUP     data this shop still has to fill in. A failure here is a job for
            a person, not a bug, and each line says which job.
"""

results = []


def check(section, label, ok, detail=""):
    results.append((section, label, ok, detail))
    print("  [%s] %-46s %s" % ("PASS" if ok else "FAIL", label, detail))


Config = env['pos.config'].sudo()
Module = env['ir.module.module'].sudo()
Method = env['pos.payment.method'].sudo()

print("=" * 78)
print("DEPLOYMENT CHECK   db=%s" % env.cr.dbname)
print("=" * 78)

module = Module.search([('name', '=', 'pos_retail')], limit=1)
print("\nmodule version installed: %s   state: %s"
      % (module.installed_version or '?', module.state))

print("\nCODE (from the upgrade)")

# Promotions: the campaign model grown into all three discount types
promo_fields = env['pos.retail.brand.campaign']._fields
check('code', "Promotions: discount types",
      'discount_type' in promo_fields and 'discount_value' in promo_fields,
      "percentage / fixed amount / fixed price")
check('code', "Promotions: six ways to target",
      'scope' in promo_fields and 'tag_ids' in promo_fields and 'categ_ids' in promo_fields,
      "all, products, category, brand, brand products, tags")
check('code', "Promotions: start and end carry a TIME",
      promo_fields.get('date_start') is not None
      and promo_fields['date_start'].type == 'datetime')

# Khata visibility on the orders list
order_fields = env['pos.order']._fields
check('code', "Orders list shows Unpaid (Khata)",
      'pos_retail_on_account' in order_fields,
      order_fields['pos_retail_on_account'].string if 'pos_retail_on_account' in order_fields else "missing")

# Kiosk sign-in and the logout lock
cfg_fields = Config._fields
check('code', "Kiosk Link on registers", 'pos_retail_kiosk_token' in cfg_fields)
check('code', "Signing out locks the kiosk link",
      'pos_retail_kiosk_relock_on_logout' in cfg_fields)

# Labels
label_fields = env['product.label.layout']._fields
check('code', "Labels: print without barcode", 'pos_retail_print_barcode' in label_fields)
check('code', "Labels: print without price", 'pos_retail_print_price' in label_fields)
check('code', "Labels: preview before printing",
      hasattr(env['product.label.layout'], 'action_pos_retail_preview'))

# Access
check('code', "Permission: Adjust Customer Khata",
      bool(env.ref('pos_retail.perm_khata_adjust', raise_if_not_found=False)))

print("\nSETUP (data this shop fills in)")

pay_later = Method.search([]).filtered(lambda m: m.type == 'pay_later')
renamed = pay_later and all(m.name == "Customer Credit" for m in pay_later)
check('setup', "Pay-later method renamed to Customer Credit", bool(renamed),
      "" if renamed else "run scripts/rename_customer_account.py (close tills first)")

for cfg in Config.search([]):
    check('setup', "%s: has a discount product" % cfg.name[:28],
          bool(cfg.discount_product_id),
          "" if cfg.discount_product_id else "run scripts/fix_discount_product.py")
    check('setup', "%s: asks for a cashier PIN" % cfg.name[:28],
          cfg.module_pos_hr,
          "" if cfg.module_pos_hr else "tick 'Log in with Employees' (close the session first)")
    check('setup', "%s: kiosk link set up" % cfg.name[:28],
          bool(cfg.pos_retail_kiosk_user_id),
          "" if cfg.pos_retail_kiosk_user_id else "run scripts/commission_till_signin.py")

parents = env['res.company'].sudo().search([('child_ids', '!=', False)])
stray = Config.search([('company_id', 'in', parents.ids), ('active', '=', True)])
check('setup', "Parent company has no active register", not stray,
      "" if not stray else "%s -- close its session, then retire_parent_register.py"
      % ", ".join(stray.mapped('name')))

no_pin = env['hr.employee'].sudo().search([('pin', '=', False)])
check('setup', "Every employee has a PIN", not no_pin,
      "" if not no_pin else "%s without one -- run scripts/set_employee_pins.py" % len(no_pin))

print()
print("=" * 78)
code_bad = [r for r in results if r[0] == 'code' and not r[2]]
setup_bad = [r for r in results if r[0] == 'setup' and not r[2]]
print("%s checks, %s code failures, %s setup items outstanding"
      % (len(results), len(code_bad), len(setup_bad)))
if code_bad:
    print()
    print("THE UPGRADE DID NOT FULLY LAND. Run the pull and the -u pos_retail")
    print("upgrade again, and check it ends without an error:")
    for _s, label, _ok, _d in code_bad:
        print("  - %s" % label)
elif not setup_bad:
    print()
    print("Everything is in place.")
else:
    print()
    print("Code is up to date. Outstanding jobs for a person:")
    for _s, label, _ok, detail in setup_bad:
        print("  - %s%s" % (label, ": " + detail if detail else ""))
print("=" * 78)
