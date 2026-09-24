"""
FULL WIPE of all products, vendors, customers, and every record that
touches them -- invoices, bills, payments, POS orders & sessions, sale &
purchase orders, stock moves/pickings/quants/lots, bank statement lines,
and every pos_retail history table (inventory movements, discount logs,
khata payments, ledger adjustments, customer refunds, vendor returns).

Keeps: res.company (every company/branch), res.users (every login, and
its own linked partner record), and all CONFIGURATION -- taxes, chart of
accounts, POS configs, warehouses, thermal label presets, discount roles,
etc. Nothing in this script touches res_company or res_users.

    venv/Scripts/python.exe odoo/odoo-bin shell -c odoo.conf -d <db> --no-http \
        < custom_addons/pos_retail/scripts/factory_reset_products_partners.py

On the server:
    sudo -u odoo /opt/odoo/venv/bin/python3 /opt/odoo/odoo/odoo-bin shell \
        -c /etc/odoo/odoo.conf -d ostore_live --no-http \
        < /opt/odoo/custom_addons/pos_retail/scripts/factory_reset_products_partners.py

READ THIS BEFORE SETTING APPLY = True.

This is NOT the same kind of operation as the other scripts in this folder.
Those close sessions or commission a branch through Odoo's own business
logic. This one deletes rows with raw SQL -- the only way to actually
remove POSTED invoices, DONE stock moves, and CLOSED POS orders, since
Odoo's ORM refuses to unlink() any of those by design (in a real, live
business they are meant to be permanent). Raw SQL does not check fiscal
lock dates, does not care whether an invoice was already filed with a tax
authority, and leaves gaps in official document numbering.

Use this to reset TEST or PILOT data before genuinely going live. Never
run it against a database with real, already-reported financial records
you need to keep -- there is no undo here except a backup restore.

BEFORE running with APPLY = True, take a real backup:
    sudo -u postgres pg_dump -Fc <db> > ~/backup_<db>_$(date +%Y%m%d_%H%M).dump

Scope: every product (product.template/product.product), and every
partner with customer_rank > 0 or supplier_rank > 0 -- plus that partner's
own child contacts/addresses -- across ALL companies/branches, are
deleted, along with every record anywhere in Odoo that would otherwise
block that deletion. A company's or user's own partner record is never
touched, even if it were somehow rank-tagged as a customer/vendor: it is
explicitly excluded, and res_company.partner_id / res_users.partner_id
are RESTRICT constraints at the database level, so Postgres itself would
refuse the delete as a second line of defense.

Deletion order matters and was verified against this database's actual
foreign-key graph (information_schema), not assumed -- several of these
relationships (stock_move.picking_id, stock_move_line.move_id,
account_payment.move_id, pos_order.session_id) are SET NULL rather than
CASCADE, meaning deleting the parent does NOT clean up the child; each
had to be listed explicitly.
"""

APPLY = False

cr = env.cr


def count(sql, params=None):
    cr.execute(sql, params or [])
    return cr.fetchone()[0]


print()
print("=" * 78)
print("FACTORY RESET: products, vendors, customers, and their history"
      + ("" if APPLY else "   (DRY RUN -- nothing written)"))
print("=" * 78)

# Partners in scope: customer/vendor contacts, expanded to their whole
# family (child addresses etc. via commercial_partner_id), and explicitly
# never a company's or a user's own partner record.
cr.execute("""
    SELECT id FROM res_partner
    WHERE (customer_rank > 0 OR supplier_rank > 0)
      AND id NOT IN (SELECT partner_id FROM res_company WHERE partner_id IS NOT NULL)
      AND id NOT IN (SELECT partner_id FROM res_users WHERE partner_id IS NOT NULL)
""")
root_ids = [r[0] for r in cr.fetchall()]

partner_ids = []
if root_ids:
    cr.execute("""
        SELECT id FROM res_partner
        WHERE (commercial_partner_id = ANY(%s) OR id = ANY(%s))
          AND id NOT IN (SELECT partner_id FROM res_company WHERE partner_id IS NOT NULL)
          AND id NOT IN (SELECT partner_id FROM res_users WHERE partner_id IS NOT NULL)
    """, (root_ids, root_ids))
    partner_ids = [r[0] for r in cr.fetchall()]

customer_count = count("SELECT COUNT(*) FROM res_partner WHERE id = ANY(%s) AND customer_rank > 0", (partner_ids,)) if partner_ids else 0
vendor_count = count("SELECT COUNT(*) FROM res_partner WHERE id = ANY(%s) AND supplier_rank > 0", (partner_ids,)) if partner_ids else 0
product_count = count("SELECT COUNT(*) FROM product_template")

print()
print("Will delete:")
print("  %5d product templates (and their variants)" % product_count)
print("  %5d partner records total -- %d customer(s), %d vendor(s), rest are"
      % (len(partner_ids), customer_count, vendor_count))
print("        their child contacts/addresses")
print()
print("...and everything referencing them:")
for table, label in [
    ("pos_order", "POS orders"),
    ("pos_session", "POS sessions"),
    ("sale_order", "Sale orders / quotations"),
    ("purchase_order", "Purchase orders"),
    ("account_move", "Invoices / bills / journal entries"),
    ("account_payment", "Payments"),
    ("account_partial_reconcile", "Payment/invoice reconciliations"),
    ("account_bank_statement_line", "Bank statement lines"),
    ("stock_picking", "Stock transfers"),
    ("stock_move", "Stock moves"),
    ("stock_quant", "Stock on-hand quantities"),
    ("stock_lot", "Lots / serial numbers"),
    ("pos_retail_inventory_movement", "pos_retail inventory movement log"),
    ("pos_retail_discount_log", "pos_retail order discount log"),
    ("pos_retail_line_discount_log", "pos_retail line discount log"),
    ("pos_retail_customer_refund", "pos_retail customer refunds"),
    ("pos_retail_vendor_return", "pos_retail vendor returns"),
    ("pos_retail_khata_payment", "pos_retail khata payments"),
    ("pos_retail_ledger_adjustment", "pos_retail ledger adjustments"),
]:
    print("  %6d  %s" % (count(f"SELECT COUNT(*) FROM {table}"), label))

if not APPLY:
    print()
    print("=" * 78)
    print("Nothing was written. Take a backup, read the warning at the top of")
    print("this file, then set APPLY = True, or pipe it:")
    print("  sed 's/^APPLY = False/APPLY = True/' <this file> | odoo-bin shell ...")
    print("=" * 78)
else:
    print()
    print("Deleting...")
    try:
        with cr.savepoint():
            # 1. pos_retail's own audit-trail / history tables
            cr.execute("DELETE FROM pos_retail_inventory_movement")
            cr.execute("DELETE FROM pos_retail_discount_log")
            cr.execute("DELETE FROM pos_retail_line_discount_log")
            cr.execute("DELETE FROM pos_retail_customer_refund")   # cascades .item
            cr.execute("DELETE FROM pos_retail_vendor_return")     # cascades .item
            cr.execute("DELETE FROM pos_retail_khata_payment")     # cascades .line
            cr.execute("DELETE FROM pos_retail_ledger_adjustment")

            # 2. Stock layer -- must precede product deletion (product_id is
            #    RESTRICT on stock_move/stock_quant/stock_lot/stock_scrap).
            #    None of these cascade automatically from their picking, so
            #    each is listed explicitly.
            cr.execute("DELETE FROM stock_move_line")
            cr.execute("DELETE FROM stock_move")
            cr.execute("DELETE FROM stock_quant")
            cr.execute("DELETE FROM stock_lot")
            cr.execute("DELETE FROM stock_scrap")
            cr.execute("DELETE FROM stock_picking")

            # 3. Orders -- their lines cascade automatically
            cr.execute("DELETE FROM purchase_order")
            cr.execute("DELETE FROM sale_order")
            cr.execute("DELETE FROM pos_order")
            cr.execute("DELETE FROM pos_session")

            # 4. Accounting -- payments and bank statement lines do NOT
            #    cascade from account_move, so they're deleted explicitly
            cr.execute("DELETE FROM account_payment")
            cr.execute("DELETE FROM account_bank_statement_line")
            cr.execute("DELETE FROM account_bank_statement")
            cr.execute("DELETE FROM payment_transaction")
            cr.execute("DELETE FROM payment_token")
            # Payment-to-invoice matchings RESTRICT deletion of the journal
            # items they link, so they must go before account_move.
            cr.execute("DELETE FROM account_partial_reconcile")
            cr.execute("DELETE FROM account_full_reconcile")
            cr.execute("DELETE FROM account_move")   # cascades account_move_line

            # 5. Loyalty reward configs that pin a specific product: clear
            #    just that link (not the whole reward) to unblock deletion
            cr.execute("UPDATE loyalty_reward SET discount_line_product_id = NULL "
                       "WHERE discount_line_product_id IS NOT NULL")
            cr.execute("DELETE FROM product_combo_item")

            # 6. Master data itself
            cr.execute("DELETE FROM product_template")   # cascades product_product
            if partner_ids:
                cr.execute("DELETE FROM res_partner WHERE id = ANY(%s)", (partner_ids,))

        cr.commit()
        print("Done. Committed.")
    except Exception as exc:
        print("FAILED -- rolled back, nothing was written.")
        print("Reason: %s" % str(exc)[:400])
        print()
        print("This usually means some table still references a product or")
        print("partner that this script didn't anticipate. The error above")
        print("names the table -- add a DELETE for it above and try again.")

print("=" * 78)
