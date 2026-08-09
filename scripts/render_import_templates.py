# -*- coding: utf-8 -*-
"""Render the import templates to disk so you can open them in Excel.

    venv\\Scripts\\python.exe odoo\\odoo-bin shell -c odoo.conf -d OStore --no-http < custom_addons/pos_retail/scripts/render_import_templates.py

A development aid only. Nothing ships these files: the real ones are built per
download by controllers/import_template.py, against the database the user is
importing into, which is what lets the dropdowns hold the units, categories,
brands and vendors that actually exist there. Rendering them here is simply how
you eyeball the result without clicking through the web client.

The column definitions live in pos_retail/tools/import_templates.py -- edit them
there, not in the spreadsheets, which are build output.
"""
import os

from odoo.addons.pos_retail.tools import import_templates

OUT_DIR = os.path.join(os.path.expanduser("~"), "pos_retail_import_templates")


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    print("Rendering import templates for '%s':" % env.company.name)  # noqa: F821
    for key in import_templates.TEMPLATES:
        data = import_templates.build_workbook(env, key)  # noqa: F821
        path = os.path.join(OUT_DIR, import_templates.filename_for(key))
        with open(path, "wb") as fh:
            fh.write(data)
        print("  %-22s %7d bytes  ->  %s" % (key, len(data), path))
    print("done")


main()
