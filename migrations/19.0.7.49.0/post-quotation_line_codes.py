"""Drop the bracketed product code from the lines of open quotations.

New quotation lines are described by the product name alone
(models/sale_order_line.py). Quotations saved before that still read
"[MBAHRIA0001] PUTTY" on every line, and those are exactly the documents
still being printed and sent to customers.

Only open quotations (draft, sent) are touched: a confirmed order is what the
customer agreed to and stays as written. And only an exact leading
"[<that line's own product code>] " is removed, so a description someone
edited by hand keeps whatever they wrote after it, and one that never started
with the code is left alone.
"""


def migrate(cr, version):
    if not version:
        return

    from odoo import api, SUPERUSER_ID

    env = api.Environment(cr, SUPERUSER_ID, {})
    lines = env['sale.order.line'].search([
        ('order_id.state', 'in', ('draft', 'sent')),
        ('display_type', '=', False),
        ('product_id.default_code', '!=', False),
    ])
    for line in lines:
        prefix = f"[{line.product_id.default_code}] "
        if line.name and line.name.startswith(prefix):
            line.name = line.name[len(prefix):]
