"""Give each branch its own customers and vendors.

Same shape as the product split: the original keeps the branch that holds its
history, a copy is created for the other branch.

Never touched:
  * company records (res.company.partner_id) - they ARE the branches;
  * user records - a login must resolve to one partner across the database;
  * employees - staff belong to a company already and are not buyers.
"""
P = env['res.partner'].sudo()
MAIN = env['res.company'].sudo().browse(1)     # Cash & Carry
BRANCH = env['res.company'].sudo().browse(2)   # Cusotmer 1

protected = (env['res.company'].sudo().search([]).partner_id
             | env['res.users'].sudo().with_context(active_test=False).search([]).partner_id)

targets = P.search([
    ('company_id', '=', False),
    ('employee', '=', False),
    '|', ('customer_rank', '>', 0), ('supplier_rank', '>', 0),
]) - protected
# The walk-in customer carries no rank but every branch needs its own.
walkin = env.ref('pos_retail.partner_walk_in_customer', raise_if_not_found=False)
if walkin and walkin not in targets and walkin not in protected:
    targets |= walkin

print(f"splitting {len(targets)} customers/vendors; protecting {len(protected)} company/user records")

Order = env['pos.order'].sudo()
done = failed = 0
for partner in targets:
    try:
        orders = Order.search([('partner_id', '=', partner.id)], limit=20)
        owner = orders.company_id[0] if orders and orders.company_id else MAIN
        other = BRANCH if owner == MAIN else MAIN

        copy = partner.copy({'name': partner.name, 'company_id': other.id})
        partner.company_id = owner.id
        env.cr.commit()
        done += 1
    except Exception as e:
        env.cr.rollback()
        failed += 1
        print(f"  FAIL '{partner.name}': {str(e)[:130]}")

# Each register needs a default customer belonging to ITS OWN branch, or the
# walk-in partner it points at is invisible to it.
if walkin:
    for cfg in env['pos.config'].sudo().search([]):
        try:
            own = P.search([('name', '=', walkin.name), ('company_id', '=', cfg.company_id.id)], limit=1)
            if own and cfg.pos_retail_default_partner_id != own:
                cfg.pos_retail_default_partner_id = own.id
                env.cr.commit()
                print(f"  '{cfg.name}' default customer -> {own.name} ({own.company_id.name})")
        except Exception as e:
            env.cr.rollback()
            print(f"  default-customer FAIL on '{cfg.name}': {str(e)[:110]}")

print(f"\nsplit={done} failed={failed}")
