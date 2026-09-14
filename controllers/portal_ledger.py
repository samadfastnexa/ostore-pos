# -*- coding: utf-8 -*-
import hashlib
import hmac
from odoo import http
from odoo.http import request


def get_ledger_token(env, partner_id):
    secret = env['ir.config_parameter'].sudo().get_param('database.secret', 'pos_retail_khata')
    msg = f'ledger_partner_{partner_id}'.encode('utf-8')
    return hmac.new(secret.encode('utf-8'), msg, hashlib.sha256).hexdigest()[:16]


class PosRetailPortalLedger(http.Controller):

    @http.route([
        '/pos_retail/portal/ledger/pdf/<int:partner_id>',
        '/pos_retail/portal/vendor/pdf/<int:partner_id>',
    ], type='http', auth='public', website=False)
    def download_public_ledger_pdf(self, partner_id, token=None, **kwargs):
        partner = request.env['res.partner'].sudo().browse(partner_id)
        if not partner.exists():
            return request.not_found()

        expected_token = get_ledger_token(request.env, partner_id)
        # Verify security token or active logged-in user session
        if token != expected_token and not request.session.uid:
            return request.make_response('Unauthorized access', status=403)

        is_vendor = '/vendor/' in request.httprequest.path
        report_name = 'pos_retail.report_vendor_statement' if is_vendor else 'pos_retail.report_customer_ledger'

        try:
            pdf = request.env['ir.actions.report'].sudo()._render_qweb_pdf(report_name, [partner.id])[0]
            clean_name = (partner.name or 'Partner').replace(' ', '_')
            prefix = 'Vendor_Statement' if is_vendor else 'Customer_Ledger'
            filename = f'{prefix}_{clean_name}.pdf'

            headers = [
                ('Content-Type', 'application/pdf'),
                ('Content-Length', len(pdf)),
                ('Content-Disposition', f'inline; filename={filename}'),
            ]
            return request.make_response(pdf, headers=headers)
        except Exception as e:
            return request.make_response(f'Error generating statement: {str(e)}', status=500)
