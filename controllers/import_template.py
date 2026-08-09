from odoo import http
from odoo.http import request

from ..tools import import_templates


class PosRetailImportTemplate(http.Controller):
    """Serve the import spreadsheets, generated per download.

    They used to be static files under static/xls. Generating them here instead
    is what lets every name-matched column carry a dropdown of the units,
    categories, brands and vendors that exist in THIS database: a static file
    cannot know what a given shop has configured, so the user was left guessing
    exact spellings and finding out only when the import failed with "No
    matching record found".

    auth='user' and no sudo: the lists are read with the caller's own rights, so
    a spreadsheet never reveals records the person downloading it could not
    already see in the interface.
    """

    @http.route(
        '/pos_retail/import-template/<string:key>.xlsx',
        type='http', auth='user', methods=['GET'], readonly=True,
    )
    def download(self, key, **kwargs):
        if key not in import_templates.TEMPLATES:
            return request.not_found()

        content = import_templates.build_workbook(request.env, key)
        filename = import_templates.filename_for(key)
        return request.make_response(content, headers=[
            ('Content-Type',
             'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'),
            ('Content-Length', len(content)),
            ('Content-Disposition', http.content_disposition(filename)),
            # The lists are built from live data, so a cached copy would go
            # stale the moment a category is added.
            ('Cache-Control', 'no-store'),
        ])
